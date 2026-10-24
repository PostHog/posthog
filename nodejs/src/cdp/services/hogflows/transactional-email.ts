import { Counter } from 'prom-client'
import { z } from 'zod'

import { BareEmailAddressSchema } from '~/cdp/schema/emailFields'

export const AcceptedSendSchema = z
    .object({
        // Absent when the send uses a local template, whose own content renders as usual.
        content: z
            .object({
                subject: z.string().min(1),
                html: z.string().optional(),
                // Absent when the HTML has no text to derive, such as a single image.
                text: z.string().optional(),
            })
            .readonly()
            .refine((content) => !!content.html || !!content.text, { message: 'content needs html or text' })
            .optional(),
        from: z
            .object({
                integrationId: z.number().int(),
                email: z.string().optional(),
                name: z.string().optional(),
            })
            .readonly()
            .optional(),
        replyTo: z.array(z.string()).readonly().optional(),
        tracking: z.object({ captureEngagement: z.boolean() }).readonly(),
    })
    .readonly()

// A code send accepted by the transactional email API, carried on the run so the worker delivers
// exactly what the caller sent. It is part of the queued job format: change it only additively.
export type AcceptedSend = z.infer<typeof AcceptedSendSchema>

// What Django sends to run a transactional email's workflow once.
export const TransactionalEmailRequestSchema = z.object({
    to: BareEmailAddressSchema,
    // The person the send is tracked against. Django falls back to the recipient's address.
    distinct_id: z.string().min(1),
    // The caller's `message_data`, available to the template as `variables`.
    variables: z.record(z.string(), z.any()).default({}),
    // The caller's `Idempotency-Key`. A repeat with the same key and request returns the first send.
    idempotency_key: z.string().min(1).max(255).optional(),
    send: AcceptedSendSchema.optional(),
})

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
    | 'error'

export const transactionalEmailRequestsTotal = new Counter({
    name: 'cdp_transactional_email_requests_total',
    help: 'Requests from Django to run a transactional email, by outcome. Every outcome except `queued` means this request queued no email.',
    labelNames: ['outcome'],
})
