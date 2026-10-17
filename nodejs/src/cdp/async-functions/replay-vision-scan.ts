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

registerAsyncFunction('postHogReplayVisionScan', {
    execute: (args, context, result) => {
        const [payload] = args as [Record<string, any> | undefined]

        if (typeof payload?.session_id !== 'string' || !payload.session_id) {
            throw new Error("postHogReplayVisionScan call missing 'session_id' property")
        }

        // Both come from the flow-spawned invocation, never from step inputs: the hog_flow_id claim is what
        // the endpoint trusts, and the dispatch key is also the origin key that wakes this step when the scan ends.
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const idempotencyKey = workflowStepDispatchKeyFromInvocation(context.invocation)
        if (!hogFlow?.id || !idempotencyKey) {
            throw new Error('postHogReplayVisionScan only runs inside a workflow')
        }

        const jwt = getVisionRequestJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Replay Vision scans from a workflow are not configured in this environment (WORKFLOW_VISION_REQUEST_JWT_SECRET unset)'
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
                session_id: payload.session_id,
                setup: payload.setup,
                wait_for_session_end: payload.wait_for_session_end !== false,
                idempotency_key: idempotencyKey,
            }),
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogReplayVisionScan' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogReplayVisionScan(${JSON.stringify(args[0], null, 2)})`,
        })

        return { status: 202, body: { request_id: 'mock-request-id', status: 'running' } }
    },
})
