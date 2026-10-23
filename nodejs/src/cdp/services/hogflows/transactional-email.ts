import { Counter } from 'prom-client'
import { z } from 'zod'

import {
    BareEmailAddressSchema,
    EmailHeaderSchema,
    EmailTagSchema,
    MAX_EMAIL_COPIES,
    MAX_EMAIL_HEADERS,
    MAX_EMAIL_TAGS,
} from '~/cdp/schema/emailFields'
import { HogFlow } from '~/cdp/schema/hogflow'

import { IntegrationManagerService } from '../managers/integration-manager.service'
import { PolicyCode, SendCandidate } from '../messaging/email-send-policy'
import { EmailSenderConfiguration, selectEmailSenderIntegrationId } from '../messaging/email-sender-selection'
import { emailPauseMetadata } from './hogflow-functions.service'
import { IdempotencyKeys } from './idempotency-keys'

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
                // The project's default sender, chosen because the caller named none.
                isDefault: z.boolean().optional(),
            })
            .readonly()
            .optional(),
        replyTo: z.array(z.string()).readonly().optional(),
        cc: z.array(BareEmailAddressSchema).max(MAX_EMAIL_COPIES).readonly().optional(),
        bcc: z.array(BareEmailAddressSchema).max(MAX_EMAIL_COPIES).readonly().optional(),
        headers: z.array(EmailHeaderSchema.readonly()).max(MAX_EMAIL_HEADERS).readonly().optional(),
        tags: z.array(EmailTagSchema.readonly()).max(MAX_EMAIL_TAGS).readonly().optional(),
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
    // Set by `messaging/send/email/`. Absent for `messaging_templates/{id}/send/`.
    route: z.literal('send_email').optional(),
})

export type TransactionalEmailRequest = z.infer<typeof TransactionalEmailRequestSchema>

/**
 * What an idempotency key is bound to. A key reused on the other send route, or with other code
 * content, is another request. A template send on the original route keeps the parts it had before
 * code sends, so a retry across a deploy still matches the key it reserved.
 */
export function transactionalSendFingerprint(hogFlowId: string, request: TransactionalEmailRequest): string {
    const { to, distinct_id: distinctId, variables, send, route } = request
    const parts: unknown[] = [hogFlowId, to, distinctId, variables]
    // The default sender can change before a retry, which must still replay.
    const requested = send?.from?.isDefault ? { ...send, from: null } : send
    return IdempotencyKeys.fingerprint(send || route ? [...parts, requested ?? null, route ?? null] : parts)
}

export const NOT_SENDABLE = {
    error: 'transactional_email_paused',
    code: 'transactional_email_paused',
    detail: "The email's workflow isn't an active transactional email.",
    why: 'PostHog sends a transactional email only while its workflow is active.',
    fix: "Turn the email's workflow back on, then send again.",
}

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
    | PolicyCode
    | 'error'

export const transactionalEmailRequestsTotal = new Counter({
    name: 'cdp_transactional_email_requests_total',
    help: 'Requests from Django to run a transactional email, by outcome. Every outcome except `queued` means this request queued no email.',
    labelNames: ['outcome'],
})

/**
 * What the delivery's send checks will see, known when the send is accepted: the sender the email step
 * resolves to for this run, and the recipients. The caller's `send.from` replaces the step's sender, as it
 * does at delivery.
 */
export async function transactionalSendCandidate(
    hogFlow: HogFlow,
    invocationId: string,
    to: string,
    send: AcceptedSend | undefined,
    integrationManager: Pick<IntegrationManagerService, 'get'>
): Promise<SendCandidate> {
    const from = send?.from ?? emailStepSender(hogFlow)
    return {
        teamId: hogFlow.team_id,
        workflowMetadata: emailPauseMetadata(hogFlow),
        sender: from ? await integrationManager.get(selectEmailSenderIntegrationId(invocationId, from)) : null,
        // Every copy is a recipient, so suppression covers the whole send.
        recipients: [to, ...(send?.cc ?? []), ...(send?.bcc ?? [])],
    }
}

type RecipientField = 'to' | 'cc' | 'bcc'

/** The request field that holds every refused address, or null when they sit in more than one field. */
export function refusedRecipientField(
    refusedAddresses: string[],
    to: string,
    send: AcceptedSend | undefined
): RecipientField | null {
    const held: Record<RecipientField, readonly string[]> = { to: [to], cc: send?.cc ?? [], bcc: send?.bcc ?? [] }
    const holding = (Object.keys(held) as RecipientField[]).filter((field) =>
        refusedAddresses.some((address) => held[field].includes(address))
    )
    return holding.length === 1 ? holding[0] : null
}

function emailStepSender(hogFlow: HogFlow): EmailSenderConfiguration | null {
    const step = hogFlow.actions.find((action) => action.type === 'function_email')
    const from = step?.type === 'function_email' ? step.config.inputs?.email?.value?.from : undefined
    return typeof from?.integrationId === 'number' ? from : null
}
