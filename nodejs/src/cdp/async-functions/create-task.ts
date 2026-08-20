import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'

// The token rides the staged fetch verbatim through every engine retry (executeFetch re-queues
// the identical request), so its lifetime must cover the whole backoff chain plus queue lag,
// not one attempt. An expired token 401s, which is not retriable, so the step fails permanently.
// The claims scope it to a single team and workflow, which keeps the longer window cheap.
const TOKEN_TTL_SECONDS = 30 * 60

// Constructed on first use rather than at import so the module has no side effects beyond
// registration and tests can override env-derived config before anything reads it.
let tasksJwt: ScopedServiceJwt | undefined
const getTasksJwt = (): ScopedServiceJwt =>
    (tasksJwt ??= new ScopedServiceJwt(PosthogJwtAudience.TASKS_CREATE, defaultConfig.TASKS_CREATE_JWT_SECRET))

registerAsyncFunction('postHogCreateTask', {
    execute: (args, context, result) => {
        const [payload] = args as [Record<string, any> | undefined]

        if (!payload?.prompt || typeof payload.prompt !== 'string') {
            throw new Error("postHogCreateTask call missing 'prompt' property")
        }

        // Both come from the flow-spawned invocation, never from step inputs: the hog_flow_id
        // claim is what the endpoint trusts to resolve the workflow owner, and the action id
        // makes the idempotency key step-scoped (the run id alone is shared by every step in
        // the run, so two task steps in one workflow would dedupe against each other).
        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const actionId = context.invocation.state.actionId
        if (!hogFlow?.id || !actionId) {
            throw new Error('postHogCreateTask only runs inside a workflow')
        }

        const jwt = getTasksJwt()
        if (!jwt.enabled) {
            throw new Error('Task creation is not configured in this environment (TASKS_CREATE_JWT_SECRET unset)')
        }
        const token = jwt.mint({ team_id: context.invocation.teamId, hog_flow_id: hogFlow.id }, TOKEN_TTL_SECONDS)

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/projects/${context.invocation.teamId}/workflow_tasks/`,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
                ...payload,
                idempotency_key: `${context.invocation.id}:${actionId}`,
            }),
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogCreateTask' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogCreateTask(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 201,
            body: { id: 'mock-task-id', run_id: 'mock-task-run-id' },
        }
    },
})
