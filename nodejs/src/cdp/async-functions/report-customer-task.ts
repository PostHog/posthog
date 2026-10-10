import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { UUID_RE, callInternalApi } from './internal-api-call'

let customerTasksReportJwt: ScopedServiceJwt | undefined
const getCustomerTasksReportJwt = (): ScopedServiceJwt =>
    (customerTasksReportJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.CUSTOMER_TASKS_REPORT,
        defaultConfig.CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRET
    ))

const OUTCOMES = ['completed', 'needs_human'] as const
type Outcome = (typeof OUTCOMES)[number]

interface ReportBody {
    report: string
    outcome: Outcome
    task_id?: string
    task_run_id?: string
}

const optionalId = (value: unknown, label: string): string | undefined => {
    if (value == null || value === '') {
        return undefined
    }
    if (typeof value !== 'string') {
        throw new Error(`Enter a valid ${label}`)
    }
    return value
}

// The workflow step test panel mocks async functions by default, so `mock` runs these checks too.
// A payload the mock accepts but the endpoint rejects lets an author ship a step that only ever
// worked in the test panel.
const parseReportPayload = (args: any[]): { customerTaskId: string; body: ReportBody } => {
    const [payload] = args as [Record<string, unknown> | undefined]
    if (typeof payload?.customer_task_id !== 'string' || !payload.customer_task_id.trim()) {
        throw new Error('Enter a customer task ID')
    }
    // The task id becomes a URL segment, so only a UUID may pass. Lowercased because Django's
    // <uuid:> converter only accepts the canonical form.
    if (!UUID_RE.test(payload.customer_task_id)) {
        throw new Error('Enter a valid customer task ID')
    }
    if (typeof payload.report !== 'string' || !payload.report.trim()) {
        throw new Error('Enter a report')
    }
    const outcome = payload.outcome
    if (typeof outcome !== 'string' || !OUTCOMES.includes(outcome as Outcome)) {
        throw new Error('Choose an outcome of completed or needs_human')
    }
    const taskId = optionalId(payload.task_id, 'AI task ID')
    const taskRunId = optionalId(payload.task_run_id, 'AI task run ID')

    return {
        customerTaskId: payload.customer_task_id.toLowerCase(),
        body: {
            report: payload.report,
            outcome: outcome as Outcome,
            ...(taskId ? { task_id: taskId } : {}),
            ...(taskRunId ? { task_run_id: taskRunId } : {}),
        },
    }
}

registerAsyncFunction('postHogReportCustomerTask', {
    execute: async (args, context, result) => {
        const { customerTaskId, body } = parseReportPayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const { actionId, actionStepCount, customerTaskIdempotencyVersion } = context.invocation.state
        if (!hogFlow?.id || !actionId) {
            throw new Error('Customer task reports can only be sent inside a workflow')
        }

        // Bind the token to the trusted run and step, never to user input.
        let idempotencyKey = `${context.invocation.id}:${actionId}`
        if (customerTaskIdempotencyVersion === 1) {
            if (typeof actionStepCount !== 'number' || !Number.isSafeInteger(actionStepCount) || actionStepCount < 0) {
                throw new Error('Customer task reporting requires a valid workflow visit count. Contact support.')
            }
            idempotencyKey = `${idempotencyKey}:${actionStepCount}`
        }

        const jwt = getCustomerTasksReportJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Customer task reporting is not configured. Set CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRET on the worker and Django to matching keys.'
            )
        }
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_customer_tasks/${customerTaskId}/report/`,
            method: 'POST',
            // The task id claim pins the token to the one task in the path, so a leaked token
            // cannot report to another task before it expires.
            entityClaims: {
                hog_flow_id: hogFlow.id,
                idempotency_key: idempotencyKey,
                customer_task_id: customerTaskId,
            },
            body: JSON.stringify(body),
        })
    },
    mock: (args, logs) => {
        const { customerTaskId } = parseReportPayload(args)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Customer task report was mocked. No task was updated or permissions checked.',
        })
        // Only the field the endpoint returns, so a mapping built against a mocked test still
        // resolves live.
        return { status: 200, body: { id: customerTaskId } }
    },
})
