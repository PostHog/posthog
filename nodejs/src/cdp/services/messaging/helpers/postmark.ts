import { z } from 'zod'

import { MinimalAppMetric } from '~/cdp/types'

import { EmailTrackingCodeSigner, trackingCodeFormatCounter } from './tracking-code'

// Postmark webhooks echo custom metadata back, which makes metadata the delivery-feedback
// correlation carrier: the send path stamps the signed tracking code into X-PM-Metadata-* headers
// (stripped before delivery, so the code never reaches recipients — the same trust property as the
// SES header channel). Values cap at 80 chars and messages at 10 fields, so the code is chunked
// across numbered fields and reassembled here.
export const POSTMARK_METADATA_KEY_PREFIX = 'posthog-'
export const POSTMARK_METADATA_VALUE_LIMIT = 80
export const POSTMARK_METADATA_MAX_FIELDS = 10

export function buildPostmarkMetadataHeaders(trackingCode: string): Record<string, string> | null {
    if (!trackingCode || trackingCode.length > POSTMARK_METADATA_VALUE_LIMIT * POSTMARK_METADATA_MAX_FIELDS) {
        return null
    }
    const headers: Record<string, string> = {}
    for (let i = 0; i * POSTMARK_METADATA_VALUE_LIMIT < trackingCode.length; i++) {
        headers[`X-PM-Metadata-${POSTMARK_METADATA_KEY_PREFIX}${i + 1}`] = trackingCode.slice(
            i * POSTMARK_METADATA_VALUE_LIMIT,
            (i + 1) * POSTMARK_METADATA_VALUE_LIMIT
        )
    }
    return headers
}

export function reassemblePostmarkMetadataCode(metadata: Record<string, unknown> | undefined): string | null {
    if (!metadata) {
        return null
    }
    const chunkPattern = new RegExp(`^${POSTMARK_METADATA_KEY_PREFIX}(\\d+)$`, 'i')
    const chunks: { index: number; value: string }[] = []
    for (const [key, value] of Object.entries(metadata)) {
        const match = key.match(chunkPattern)
        if (match && typeof value === 'string') {
            chunks.push({ index: parseInt(match[1], 10), value })
        }
    }
    if (chunks.length === 0) {
        return null
    }
    // Numeric sort: object key order is not guaranteed, and a lexicographic sort would put
    // "posthog-10" before "posthog-2", corrupting every code long enough to need 10 chunks.
    chunks.sort((a, b) => a.index - b.index)
    return chunks.map((c) => c.value).join('')
}

// Loose on purpose: Postmark payload shapes vary per webhook type and gain fields over time.
// We validate only what we read.
const PostmarkEventSchema = z
    .object({
        RecordType: z.string(),
        MessageID: z.string().optional(),
        Metadata: z.record(z.string(), z.unknown()).optional(),
        Recipient: z.string().optional(), // Delivery
        Email: z.string().optional(), // Bounce / SpamComplaint
        Type: z.string().optional(), // Bounce type, e.g. HardBounce
        Description: z.string().optional(),
        Details: z.string().optional(),
        DeliveredAt: z.string().optional(),
        BouncedAt: z.string().optional(),
        Subject: z.string().optional(),
    })
    .passthrough()

export type PostmarkEvent = z.infer<typeof PostmarkEventSchema>

// Mirrors the SES mapping (Complaint → email_blocked). Open/Click are deliberately absent:
// our own pixel/redirect endpoints record engagement for these sends (directTracking), so
// processing Postmark's tracking events too would double-count — and Postmark-side open/click
// tracking should stay off for these senders anyway.
const RECORD_TYPE_TO_METRIC_NAME: Record<string, MinimalAppMetric['metric_name']> = {
    Delivery: 'email_delivered',
    Bounce: 'email_bounced',
    SpamComplaint: 'email_blocked',
}

const MAX_FIELD_LENGTH = 500

const sanitizeField = (value: string, max = MAX_FIELD_LENGTH): string => {
    // eslint-disable-next-line no-control-regex
    return value.replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, max)
}

export type PostmarkWebhookResult = {
    status: number
    body: unknown
    metrics?: {
        functionId?: string
        invocationId?: string
        actionId?: string
        parentRunId?: string
        distinctId?: string
        metricName: MinimalAppMetric['metric_name']
        properties?: Record<string, any>
        timestamp?: string
    }[]
    logEntries?: {
        functionId?: string
        invocationId?: string
        parentRunId?: string
        level: 'warn' | 'error'
        message: string
    }[]
    optOutRecipients?: {
        teamId?: string
        emailAddresses: string[]
    }[]
}

/**
 * Handles Postmark's Delivery / Bounce / SpamComplaint webhooks for `postmark`-provider senders.
 * Postmark does not sign webhook payloads; authenticity rests on two layers: the per-integration
 * HMAC token in the webhook URL (checked by the caller), and the HMAC-signed tracking code
 * reassembled from the echoed metadata — a payload without a validly signed code records nothing.
 */
export class PostmarkWebhookHandler {
    constructor(private trackingCodeSigner: EmailTrackingCodeSigner) {}

    handleWebhook(opts: { body: any }): PostmarkWebhookResult {
        const parsed = PostmarkEventSchema.safeParse(opts.body)
        if (!parsed.success) {
            return { status: 400, body: { error: 'Unrecognized payload' } }
        }
        const event = parsed.data

        const metricName = RECORD_TYPE_TO_METRIC_NAME[event.RecordType]
        if (!metricName) {
            // Open/Click (we record those ourselves), SubscriptionChange, SMTP API Error, test
            // pings from the Postmark UI — acknowledged so Postmark doesn't retry or disable.
            return { status: 200, body: { ok: true, ignored: event.RecordType } }
        }

        const code = reassemblePostmarkMetadataCode(event.Metadata)
        if (!code) {
            // The customer's Postmark server can carry mail we didn't send; those events have no
            // PostHog metadata and are expected traffic, not errors.
            return { status: 200, body: { ok: true, ignored: 'no tracking metadata' } }
        }

        // Signed-only: our send path always mints signed codes, and unlike the SES path there is
        // no payload-level signature to fall back on for integrity.
        const parsedCode = this.trackingCodeSigner.parse(code)
        if (!parsedCode || parsedCode.format !== 'signed') {
            return { status: 403, body: { error: 'Invalid tracking code' } }
        }
        trackingCodeFormatCounter.inc({ format: parsedCode.format, source: 'postmark' })
        const { functionId, invocationId, teamId, actionId, parentRunId, distinctId, isTest } = parsedCode

        const recipient = event.Recipient ?? event.Email
        const timestamp = event.DeliveredAt ?? event.BouncedAt

        const metrics: PostmarkWebhookResult['metrics'] = []
        // Test sends (the editor's "Run test") are not production activity — mirror the SES gate.
        if (!isTest) {
            metrics.push({
                functionId,
                invocationId,
                actionId,
                parentRunId,
                distinctId,
                metricName,
                properties: {
                    $email_to: recipient,
                    $email_subject: event.Subject,
                },
                timestamp,
            })
        }

        const logEntries: PostmarkWebhookResult['logEntries'] = []
        const safeActionId = actionId && /^[a-zA-Z0-9_-]+$/.test(actionId) ? actionId : undefined
        const prefix = safeActionId ? `[Action:${safeActionId}] ` : ''
        if (!isTest && event.RecordType === 'Bounce') {
            const detail = event.Description || event.Details || 'no details from Postmark'
            logEntries.push({
                functionId,
                invocationId,
                parentRunId,
                level: 'warn',
                message: `${prefix}Bounce (${sanitizeField(event.Type ?? 'unknown', 40)}) to ${sanitizeField(recipient ?? 'unknown recipient', 100)}: ${sanitizeField(detail)}`,
            })
        }
        if (!isTest && event.RecordType === 'SpamComplaint') {
            logEntries.push({
                functionId,
                invocationId,
                parentRunId,
                level: 'warn',
                message: `${prefix}Spam complaint from ${sanitizeField(recipient ?? 'unknown recipient', 100)}`,
            })
        }

        // Hard bounces opt the recipient out (mirrors SES's Permanent bounce handling) — this
        // applies to test sends too, matching the SES path.
        const optOutRecipients: PostmarkWebhookResult['optOutRecipients'] = []
        if (event.RecordType === 'Bounce' && event.Type === 'HardBounce' && teamId && event.Email) {
            optOutRecipients.push({ teamId, emailAddresses: [event.Email] })
        }

        return { status: 200, body: { ok: true }, metrics, logEntries, optOutRecipients }
    }
}
