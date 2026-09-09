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

// The workflow step test panel mocks async functions by default, so `mock` runs these checks too.
// A payload the mock accepts but the endpoint rejects lets an author ship a step that only ever
// worked in the test panel.
const parseTaskPayload = (args: any[]): { payload: Record<string, unknown>; assigneeId: number | undefined } => {
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

    return { payload, assigneeId }
}

registerAsyncFunction('postHogCreateCustomerTask', {
    execute: async (args, context, result) => {
        const { payload, assigneeId } = parseTaskPayload(args)

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
        parseTaskPayload(args)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Customer task creation was mocked. No task was created or permissions checked.',
        })
        // Only the field the endpoint returns, so a mapping built against a mocked test still
        // resolves live. The template checks the ID is a UUID, so the placeholder must be one.
        return { status: 201, body: { id: '00000000-0000-4000-8000-000000000000' } }
    },
})
