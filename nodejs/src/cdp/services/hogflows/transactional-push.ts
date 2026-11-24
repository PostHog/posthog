import { createHash } from 'crypto'
import { Counter } from 'prom-client'
import { z } from 'zod'

import { HogFlow } from '~/cdp/schema/hogflow'
import { RedisV2 } from '~/common/redis/redis-v2'

import { EncryptedFields } from '../../utils/encryption-utils'
import { requestFingerprint } from './idempotency-keys'

export const TRANSACTIONAL_PUSH_EVENT = '$transactional_push'

// Never change it: a retry inside the claim's window would get another run id and send a second time.
export const TRANSACTIONAL_PUSH_RUN_SCOPE = 'transactional-push'

// Longer than a token lives, clock tolerance included, so a token can't be used a second time before it expires.
const TOKEN_USE_TTL_SECONDS = 10 * 60

// Below Django's request timeout, so a stalled Redis can't queue a push Django already reported as failed.
const TOKEN_USE_DEADLINE_MS = 2000

export const isTokenForPerson = (claims: Record<string, unknown>, distinctId: string): boolean =>
    claims.distinct_id_sha256 === createHash('sha256').update(distinctId).digest('hex')

// Django mints a new token for every request, a retry included, so a token used twice was copied.
export const useTransactionalPushToken = async (redis: RedisV2, jti: string): Promise<'first_use' | 'used'> => {
    const result = await redis.useClient(
        { name: 'transactional-push-token-use', deadlineMs: TOKEN_USE_DEADLINE_MS },
        (client) => client.set(`@posthog/cdp/transactional-push-token/${jti}`, '1', 'EX', TOKEN_USE_TTL_SECONDS, 'NX')
    )
    return result === 'OK' ? 'first_use' : 'used'
}

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
    | 'idempotency_key_reused'
    | 'idempotency_unavailable'
    | 'not_configured'
    | 'unauthorized'
    | 'token_reused'
    | 'token_check_unavailable'
    | 'invalid_request'
    | 'not_found'
    | 'not_sendable'
    | 'quota_limited'
    | 'intake_unavailable'
    | 'message_too_large'
    | 'error'

export const transactionalPushRequestsTotal = new Counter({
    name: 'cdp_transactional_push_requests_total',
    help: 'Requests from Django to run a transactional push notification, by outcome. Every outcome except `queued` means this request queued no push.',
    labelNames: ['outcome'],
})

const FINGERPRINT_PURPOSE = 'transactional_push_idempotency_fingerprint'

// Keyed, because the variables can hold a short login code that anyone who reads the claims could guess offline from an
// unkeyed hash. One per key, so a claim signed before a key rotation still matches.
export const transactionalPushFingerprints = (
    signer: Pick<EncryptedFields, 'signatures'>,
    hogFlowId: string,
    { distinct_id, variables }: TransactionalPushRequest
): string[] => signer.signatures(FINGERPRINT_PURPOSE, requestFingerprint([hogFlowId, distinct_id, variables]))

// A token for one workflow can only run that workflow, so this only stops a push token reaching a workflow that
// someone changed to send something else.
export const sendsOnlyPush = (hogFlow: HogFlow): boolean => {
    const steps = hogFlow.actions.filter((action) => action.type !== 'trigger' && action.type !== 'exit')
    return steps.length > 0 && steps.every((action) => action.type === 'function_push')
}
