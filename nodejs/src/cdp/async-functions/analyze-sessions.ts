import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { workflowStepDispatchKeyFromInvocation } from '../utils/workflow-step-dispatch-key'

// The token rides the staged fetch verbatim through every engine retry, so it must outlive the whole
// backoff chain plus queue lag. The claims scope it to one team and workflow, which keeps the window cheap.
const TOKEN_TTL_SECONDS = 30 * 60

// Its own key, not postHogCreateTask's — see products/workflows/backend/service_jwt.py for why.
let visionRequestJwt: ScopedServiceJwt | undefined
const getVisionRequestJwt = (): ScopedServiceJwt =>
    (visionRequestJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_VISION_REQUEST,
        defaultConfig.WORKFLOW_VISION_REQUEST_JWT_SECRET
    ))

registerAsyncFunction('postHogAnalyzeSessions', {
    execute: (args, context, result) => {
        const [payload] = args as [Record<string, any> | undefined]

        if (!Array.isArray(payload?.session_ids) || payload.session_ids.length === 0) {
            throw new Error("postHogAnalyzeSessions call missing 'session_ids' property")
        }

        // Both come from the flow-spawned invocation, never from step inputs: the hog_flow_id claim is what
        // the endpoint trusts, and the dispatch key is also the origin key that wakes this step when the scan ends.
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const idempotencyKey = workflowStepDispatchKeyFromInvocation(context.invocation)
        if (!hogFlow?.id || !idempotencyKey) {
            throw new Error('postHogAnalyzeSessions only runs inside a workflow')
        }

        const jwt = getVisionRequestJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Replay vision scans from a workflow are not configured in this environment (WORKFLOW_VISION_REQUEST_JWT_SECRET unset)'
            )
        }
        const token = jwt.mint({ team_id: context.invocation.teamId, hog_flow_id: hogFlow.id }, TOKEN_TTL_SECONDS)

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/projects/${context.invocation.teamId}/workflow_vision_requests/`,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
                session_ids: payload.session_ids,
                ...(payload.scanner_id ? { scanner_id: payload.scanner_id } : {}),
                ...(payload.prompt ? { prompt: payload.prompt } : {}),
                idempotency_key: idempotencyKey,
            }),
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogAnalyzeSessions' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogAnalyzeSessions(${JSON.stringify(args[0], null, 2)})`,
        })

        return { status: 202, body: { request_id: 'mock-request-id', status: 'running' } }
    },
})
