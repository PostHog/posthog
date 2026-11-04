import { Counter, Histogram } from 'prom-client'
import { z } from 'zod'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'

export const MAX_COPY_RECIPIENTS = 10

export const RECIPIENT_ADDRESS_PATTERN =
    /^[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+)*@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/

const CopyRecipientsSchema = z
    .array(z.string().email({ pattern: RECIPIENT_ADDRESS_PATTERN }))
    .max(MAX_COPY_RECIPIENTS)
    .readonly()
    .optional()

export const AcceptedSendSchema = z
    .object({
        content: z
            .object({
                subject: z.string().min(1),
                html: z.string().optional(),
                text: z.string().optional(),
            })
            .strict()
            .readonly()
            .refine((content) => !!content.html || !!content.text, { message: 'content needs html or text' })
            .optional(),
        from: z
            .object({
                integrationId: z.number().int(),
                email: z.string().optional(),
                name: z.string().optional(),
            })
            .strict()
            .readonly()
            .optional(),
        replyTo: z.array(z.string()).readonly().optional(),
        cc: CopyRecipientsSchema,
        bcc: CopyRecipientsSchema,
        tracking: z.object({ captureEngagement: z.boolean() }).strict().readonly(),
    })
    .strict()
    .readonly()

export type AcceptedSend = z.infer<typeof AcceptedSendSchema>

export const acceptedSendEmailFields = (
    send: AcceptedSend | undefined
): Partial<CyclotronInvocationQueueParametersEmailType> => ({
    ...(send?.content && {
        subject: send.content.subject,
        html: send.content.html ?? '',
        text: send.content.text ?? '',
        preheader: '',
    }),
    ...(send?.from && { from: { ...send.from } }),
    ...(send?.replyTo && { replyTo: send.replyTo.join(', ') }),
    ...(send?.cc && { cc: send.cc.join(', ') }),
    ...(send?.bcc && { bcc: send.bcc.join(', ') }),
})

// What Django sends to run a transactional email's workflow once.
export const TransactionalEmailRequestSchema = z.object({
    to: z.string().email({ pattern: RECIPIENT_ADDRESS_PATTERN }),
    // The person the send is tracked against. Django falls back to the recipient's address.
    distinct_id: z.string().min(1),
    // The caller's `message_data`, available to the template as `variables`.
    variables: z.record(z.string(), z.any()).default({}),
    // The caller's `Idempotency-Key`. A repeat with the same key and request returns the first send.
    idempotency_key: z.string().min(1).max(255).optional(),
})

export const TEMPLATE_SEND_TOKEN_CLAIMS = { kind: undefined }
export const CODE_SEND_TOKEN_CLAIMS = { kind: 'code_send' }

export const AcceptedSendRequestSchema = TransactionalEmailRequestSchema.extend({ send: AcceptedSendSchema })

export type TransactionalEmailRequest = z.infer<typeof TransactionalEmailRequestSchema> & { send?: AcceptedSend }

export const transactionalEmailRecipients = ({ to, send }: TransactionalEmailRequest): string[] => [
    to,
    ...(send?.cc ?? []),
    ...(send?.bcc ?? []),
]

export const isRecipientFormatIssue = (issue: z.core.$ZodIssue): boolean =>
    issue.code === 'invalid_format' &&
    (issue.path[0] === 'to' || (issue.path[0] === 'send' && (issue.path[1] === 'cc' || issue.path[1] === 'bcc')))

export type TransactionalEmailOutcome =
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
    | 'sending_suspended'
    | 'sending_paused'
    | 'recipient_suppressed'
    | 'recipient_unreachable'
    | 'error'

export const transactionalEmailRequestsTotal = new Counter({
    name: 'cdp_transactional_email_requests_total',
    help: 'Requests from Django to run a transactional email, by outcome. Every outcome except `queued` means this request queued no email.',
    labelNames: ['outcome'],
})

export const TRANSACTIONAL_EMAIL_STAGES = [
    'auth',
    'validate',
    'load',
    'build',
    'idempotency',
    'checks',
    'queue_insert',
    'metrics_flush',
] as const
export type TransactionalEmailStage = (typeof TRANSACTIONAL_EMAIL_STAGES)[number]

export const transactionalEmailStageDurationMs = new Histogram({
    name: 'cdp_transactional_email_stage_duration_ms',
    help: 'Milliseconds one transactional email request spends in each stage: auth (the JWT), validate (the body), load (the team and the workflow), build (the run and its idempotency fingerprint), idempotency (every Idempotency-Key call to Valkey), checks (suspension, pause, suppression, quota and MX), queue_insert (the email queue insert), metrics_flush (the hand-off of the result and status rows to the Kafka producer, without the wait for the broker), and total. A request records only the stages it reached, so a refusal shows in the stage that refused it.',
    labelNames: ['stage'],
    buckets: [1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000],
})

// The stages of a request run back to back, so starting a stage ends the one before it. finish() records each stage
// once, with its summed time, so a stage entered twice (idempotency) still counts as one observation per request.
export class TransactionalEmailStageTimer {
    private readonly startedAt = performance.now()
    private current: { stage: TransactionalEmailStage; startedAt: number } | null = null
    private readonly durations = new Map<TransactionalEmailStage, number>()

    start(stage: TransactionalEmailStage): void {
        const now = performance.now()
        this.endCurrent(now)
        this.current = { stage, startedAt: now }
    }

    finish(): void {
        const now = performance.now()
        this.endCurrent(now)
        for (const [stage, durationMs] of this.durations) {
            transactionalEmailStageDurationMs.labels({ stage }).observe(durationMs)
        }
        transactionalEmailStageDurationMs.labels({ stage: 'total' }).observe(now - this.startedAt)
    }

    private endCurrent(now: number): void {
        if (this.current) {
            const { stage, startedAt } = this.current
            this.durations.set(stage, (this.durations.get(stage) ?? 0) + now - startedAt)
            this.current = null
        }
    }
}
