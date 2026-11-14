import { Counter } from 'prom-client'
import { z } from 'zod'

import { HogFlow } from '~/cdp/schema/hogflow'

import { IdempotencyKeys } from './idempotency-keys'

export const TRANSACTIONAL_PUSH_EVENT = '$transactional_push'

// Django mints the transactional email token with this claim for a push send, so a push token can't run an email.
export const TRANSACTIONAL_PUSH_TOKEN_CLAIMS = { kind: 'push' }

export const TransactionalPushRequestSchema = z.object({
    distinct_id: z.string().min(1).max(400),
    // The caller's `message_data`, available to the template as `variables`.
    variables: z.record(z.string(), z.any()).default({}),
    idempotency_key: z.string().min(1).max(255).optional(),
})

export type TransactionalPushRequest = z.infer<typeof TransactionalPushRequestSchema>

export type TransactionalPushOutcome =
    | 'queued'
    | 'replayed'
    | 'idempotency_key_in_flight'
    | 'idempotency_key_reused'
    | 'idempotency_unavailable'
    | 'not_configured'
    | 'unauthorized'
    | 'invalid_request'
    | 'not_found'
    | 'not_sendable'
    | 'quota_limited'
    | 'error'

export const transactionalPushRequestsTotal = new Counter({
    name: 'cdp_transactional_push_requests_total',
    help: 'Requests from Django to run a transactional push notification, by outcome. Every outcome except `queued` means this request queued no push.',
    labelNames: ['outcome'],
})

export const transactionalPushFingerprint = (
    hogFlowId: string,
    { distinct_id, variables }: TransactionalPushRequest
): string => IdempotencyKeys.fingerprint([hogFlowId, distinct_id, variables])

// A token for one workflow can only run that workflow, so this only stops a push token reaching a workflow that
// someone changed to send something else.
export const sendsOnlyPush = (hogFlow: HogFlow): boolean => {
    const steps = hogFlow.actions.filter((action) => action.type !== 'trigger' && action.type !== 'exit')
    return steps.length > 0 && steps.every((action) => action.type === 'function_push')
}
