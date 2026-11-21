import { Counter } from 'prom-client'
import { z } from 'zod'

import { BatchSendSchema, TransactionalEmailRequestSchema } from './transactional-email'

export const TEMPLATE_BATCH_TOKEN_CLAIMS = { kind: 'template_batch' }
export const CODE_SEND_BATCH_TOKEN_CLAIMS = { kind: 'code_send_batch' }

export const BATCH_MAX_RECIPIENTS = 100

// Each recipient's run holds its own copy of the shared and its own top-level variables, while nested values stay shared
// between the copies. The batch bounds the sum, so a small body with many keys cannot multiply into a large heap.
export const BATCH_VARIABLE_KEYS_MAX = 50_000

// Django drops a forwarded call after 30 s. A batch still short of its publish this long after it arrived publishes
// nothing, so no email goes out for a call Django already reported as failed.
export const BATCH_PUBLISH_DEADLINE_MS = 20_000

const Variables = z.record(z.string(), z.any())
const IdempotencyKey = z.string().min(1).max(255)

// The address and the person are checked per recipient, so one bad recipient refuses only its own result.
const BatchRecipient = z.object({ to: z.unknown(), distinct_id: z.unknown(), idempotency_key: IdempotencyKey })

const hasUniqueKeys = (recipients: { idempotency_key: string }[]): boolean =>
    new Set(recipients.map((recipient) => recipient.idempotency_key)).size === recipients.length

const recipientsOf = <T extends { idempotency_key: string }>(recipient: z.ZodType<T>) =>
    z
        .array(recipient)
        .min(1)
        .max(BATCH_MAX_RECIPIENTS)
        .refine(hasUniqueKeys, { message: 'idempotency_key must be unique within a batch' })

// What Django sends to run one email for many recipients. Strict, so a field a batch never takes (a send time, copies,
// attachments) refuses the whole call instead of reaching a recipient's run.
export const TemplateBatchRequestSchema = z
    .object({
        variables: Variables.default({}),
        recipients: recipientsOf(BatchRecipient.extend({ variables: Variables.optional() }).strict()),
    })
    .strict()

export const CodeSendBatchRequestSchema = z
    .object({
        variables: Variables.default({}),
        send: BatchSendSchema,
        recipients: recipientsOf(BatchRecipient.strict()),
    })
    .strict()

export type TransactionalEmailBatchRequest = {
    variables: Record<string, any>
    send?: z.infer<typeof BatchSendSchema>
    recipients: { to?: unknown; distinct_id?: unknown; idempotency_key: string; variables?: Record<string, any> }[]
}
export type BatchRecipient = TransactionalEmailBatchRequest['recipients'][number]

export const BatchSlotRequestSchema = TransactionalEmailRequestSchema.omit({ scheduled_at: true }).extend({
    idempotency_key: IdempotencyKey,
    send: BatchSendSchema.optional(),
})

export const copiedVariableKeys = (batch: TransactionalEmailBatchRequest): number => {
    const shared = Object.keys(batch.variables).length
    return batch.recipients.reduce(
        (total, recipient) => total + shared + Object.keys(recipient.variables ?? {}).length,
        0
    )
}

// The same request a single send to this recipient makes, so a single send and a batch recipient replay each other.
export const slotRequestOf = (batch: TransactionalEmailBatchRequest, recipient: BatchRecipient): unknown => ({
    to: recipient.to,
    distinct_id: recipient.distinct_id,
    idempotency_key: recipient.idempotency_key,
    variables: { ...batch.variables, ...recipient.variables },
    ...(batch.send && { send: batch.send }),
})

export const transactionalEmailBatchRequestsTotal = new Counter({
    name: 'cdp_transactional_email_batch_requests_total',
    help: 'Batch email requests from Django, by outcome: answered (with a result per recipient), over_capacity (the pod already ran its share of batches), batch_unavailable (the team is not on async intake), or another whole-call refusal, which produces nothing. Recipients count in cdp_transactional_email_requests_total with route batch.',
    labelNames: ['outcome'],
})

export class BatchCapacity {
    private admitted = 0

    constructor(private readonly maxRequests: number) {}

    admit(): (() => void) | null {
        if (this.admitted >= this.maxRequests) {
            return null
        }
        this.admitted++
        return () => {
            this.admitted--
        }
    }
}
