import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { callInternalApi } from './internal-api-call'

let customerTasksJwt: ScopedServiceJwt | undefined
const getCustomerTasksJwt = (): ScopedServiceJwt =>
    (customerTasksJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.CUSTOMER_TASKS_CREATE,
        defaultConfig.CUSTOMER_TASKS_CREATE_JWT_SECRET
    ))

registerAsyncFunction('postHogCreateCustomerTask', {
    execute: async (args, context, result) => {
        const [payload] = args as [Record<string, unknown> | undefined]
        if (typeof payload?.name !== 'string' || !payload.name.trim()) {
            throw new Error('Enter a task name')
        }

        const assigneeId = payload.assigned_to_id === undefined ? undefined : Number(payload.assigned_to_id)
        if (
            assigneeId !== undefined &&
            (!['number', 'string'].includes(typeof payload.assigned_to_id) ||
                !Number.isSafeInteger(assigneeId) ||
                assigneeId <= 0)
        ) {
            throw new Error('Enter a valid numeric assignee user ID')
        }

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const actionId = context.invocation.state.actionId
        if (!hogFlow?.id || !actionId) {
            throw new Error('Customer analytics tasks can only be created inside a workflow')
        }

        const jwt = getCustomerTasksJwt()
        if (!jwt.enabled) {
            throw new Error('Customer task creation is not configured (CUSTOMER_TASKS_CREATE_JWT_SECRET unset)')
        }
        // Bind both the request and token to the trusted run and step, never to user input.
        const idempotencyKey = `${context.invocation.id}:${actionId}`
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_customer_tasks/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id, idempotency_key: idempotencyKey },
            body: JSON.stringify({ ...payload, assigned_to_id: assigneeId, idempotency_key: idempotencyKey }),
        })
    },
    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Customer task creation was mocked. No task was created or permissions checked.',
        })
        return { status: 201, body: { ...args[0], id: '00000000-0000-4000-8000-000000000000', status: 'open' } }
    },
})
