import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { workflowStepDispatchKeyFromInvocation } from '../utils/workflow-step-dispatch-key'

// Same lifetime reasoning as create-task.ts: the token rides every engine retry of the staged fetch.
const TOKEN_TTL_SECONDS = 30 * 60

// Its own key, not postHogCreateTask's — see products/workflows/backend/service_jwt.py for why.
let notifyJwt: ScopedServiceJwt | undefined
const getNotifyJwt = (): ScopedServiceJwt =>
    (notifyJwt ??= new ScopedServiceJwt(PosthogJwtAudience.WORKFLOW_NOTIFY, defaultConfig.WORKFLOW_NOTIFY_JWT_SECRET))

registerAsyncFunction('postHogNotifyOwner', {
    execute: (args, context, result) => {
        const [payload] = args as [Record<string, any> | undefined]

        if (!payload?.title || typeof payload.title !== 'string') {
            throw new Error("postHogNotifyOwner call missing 'title' property")
        }

        // The hog_flow_id claim is what the endpoint trusts to resolve the owner; the dispatch key
        // scopes the idempotency key to this step and visit so a retry cannot notify twice.
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const idempotencyKey = workflowStepDispatchKeyFromInvocation(context.invocation)
        if (!hogFlow?.id || !idempotencyKey) {
            throw new Error('postHogNotifyOwner only runs inside a workflow')
        }

        const jwt = getNotifyJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Notifying the workflow owner is not configured in this environment (WORKFLOW_NOTIFY_JWT_SECRET unset)'
            )
        }
        const token = jwt.mint({ team_id: context.invocation.teamId, hog_flow_id: hogFlow.id }, TOKEN_TTL_SECONDS)

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/projects/${context.invocation.teamId}/workflow_notifications/`,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ ...payload, idempotency_key: idempotencyKey }),
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogNotifyOwner' was mocked. No notification was sent. Arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogNotifyOwner(${JSON.stringify(args[0], null, 2)})`,
        })

        return { status: 202, body: {} }
    },
})
