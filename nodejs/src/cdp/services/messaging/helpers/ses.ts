import crypto from 'node:crypto'
import { z } from 'zod'

import { MinimalAppMetric } from '~/cdp/types'
import { parseJSON } from '~/utils/json-parse'
import { logger } from '~/utils/logger'
import { fetch } from '~/utils/request'

import { parseEmailTrackingCode } from './tracking-code'

/**
 * ---------- SNS envelope types ----------
 * If raw_message_delivery=false (default), SNS wraps your message in this envelope.
 */
const SnsEnvelopeSchema = z.object({
    Type: z.enum(['SubscriptionConfirmation', 'Notification', 'UnsubscribeConfirmation']),
    MessageId: z.string(),
    Token: z.string().optional(),
    TopicArn: z.string(),
    Subject: z.string().optional(),
    Message: z.string(), // either SES event JSON (Notification) or a confirmation message
    Timestamp: z.string(),
    SignatureVersion: z.enum(['1']),
    Signature: z.string(),
    SigningCertURL: z.string().url(),
    UnsubscribeURL: z.string().url().optional(),
})

export type SnsEnvelope = z.infer<typeof SnsEnvelopeSchema>

/**
 * ---------- SES event types ----------
 * AWS posts an array of records in the "Message" (or directly as body if raw_message_delivery=true).
 * We model the common fields and create specific event detail types.
 */
const SesMailSchema = z.object({
    timestamp: z.string(),
    source: z.string(), // From address
    messageId: z.string(),
    destination: z.array(z.string()),
    headersTruncated: z.boolean().optional(),
    headers: z.array(z.object({ name: z.string(), value: z.string() })).optional(),
    tags: z.record(z.string(), z.array(z.string())).optional(), // your message tags: { user_id: ["u_123"] }
})

const SesCommonEventBase = z.object({
    eventType: z.enum([
        'Send',
        'Reject',
        'Bounce',
        'Complaint',
        'Delivery',
        'Open',
        'Click',
        'RenderingFailure',
        'DeliveryDelay',
    ]),
    mail: SesMailSchema,
})

const SesOpenEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Open'),
    open: z.object({
        ipAddress: z.string().optional(),
        userAgent: z.string().optional(),
        timestamp: z.string(),
    }),
})

const SesClickEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Click'),
    click: z.object({
        ipAddress: z.string().optional(),
        link: z.string(),
        userAgent: z.string().optional(),
        timestamp: z.string(),
    }),
})

// SES documents 50 recipients as the per-send maximum, so cap log fan-out at 50.
// Anything beyond that is either a schema change or malformed input, and the summary
// line below communicates the truncation without losing opt-out or metric signal.
// Truncate at the log-format site rather than rejecting the whole payload at the
// Zod layer so oversized records still get their metrics counted and opt-outs
// processed; only the log fan-out is bounded.
const MAX_RECIPIENTS_PER_EVENT = 50

const SesDeliveryEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Delivery'),
    delivery: z.object({
        processingTimeMillis: z.number().optional(),
        smtpResponse: z.string().optional(),
        reportingMTA: z.string().optional(),
        timestamp: z.string(),
        recipients: z.array(z.string()).optional(),
    }),
})

const SesBounceEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Bounce'),
    bounce: z.object({
        bounceType: z.enum(['Undetermined', 'Permanent', 'Transient']),
        bounceSubType: z.string().optional(),
        bouncedRecipients: z.array(
            z.object({
                emailAddress: z.string(),
                action: z.string().optional(),
                status: z.string().optional(),
                diagnosticCode: z.string().optional(),
            })
        ),
        timestamp: z.string(),
        reportingMTA: z.string().optional(),
    }),
})

const SesComplaintEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Complaint'),
    complaint: z.object({
        complainedRecipients: z.array(z.object({ emailAddress: z.string() })),
        timestamp: z.string(),
        complaintFeedbackType: z.string().optional(),
        userAgent: z.string().optional(),
        feedbackId: z.string().optional(),
    }),
})

const SesRenderingFailureSchema = SesCommonEventBase.extend({
    eventType: z.literal('RenderingFailure'),
    renderingFailure: z.object({
        errorMessage: z.string(),
        templateName: z.string().optional(),
    }),
})

const SesSendEventSchema = SesCommonEventBase.extend({ eventType: z.literal('Send') })
const SesRejectEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Reject'),
    reject: z.object({ reason: z.string().optional() }).optional(),
})

// Accepted-but-unmodeled: we acknowledge the event so SNS doesn't retry forever, but we
// don't surface details. SES emits DeliveryDelay on soft failures (e.g. destination MTA
// greylisting) that resolve themselves, so the extra log noise would outweigh the signal.
const SesDeliveryDelayEventSchema = SesCommonEventBase.extend({ eventType: z.literal('DeliveryDelay') })

const SesEventRecordSchema = z.union([
    SesOpenEventSchema,
    SesClickEventSchema,
    SesDeliveryEventSchema,
    SesBounceEventSchema,
    SesComplaintEventSchema,
    SesRenderingFailureSchema,
    SesSendEventSchema,
    SesRejectEventSchema,
    SesDeliveryDelayEventSchema,
])

const SesEventBatchSchema = z.array(SesEventRecordSchema)

export type SesEventRecord = z.infer<typeof SesEventRecordSchema>

// email_sent is recorded synchronously in email.service.ts when the email is sent,
// so we don't record it again from SES Send webhooks to avoid double counting.
const EVENT_TYPE_TO_METRIC_NAME: Partial<Record<SesEventRecord['eventType'], MinimalAppMetric['metric_name']>> = {
    Open: 'email_opened',
    Click: 'email_link_clicked',
    Delivery: 'email_delivered',
    Bounce: 'email_bounced',
    Complaint: 'email_blocked',
    RenderingFailure: 'email_failed',
    Reject: 'email_failed',
}

export type SesEventLogLine = {
    level: 'info' | 'warn' | 'error'
    message: string
    // ISO timestamp of the originating SES event. Used as the log entry timestamp so
    // log order reflects when the event actually happened and SNS retries dedupe.
    timestamp: string
}

// Cap each interpolated SES field so a huge user-agent or diagnostic string can't blow up
// a log row. 1 KB is generous for anything SES produces in practice.
const MAX_SES_FIELD_LENGTH = 1024

// Strip control chars, neutralize rich-log bracket tokens (`[Action:…]`, `[Person:…]` etc.
// that the workflow logs viewer renders as clickable UI elements), and cap length.
const sanitizeSesField = (value: string, max = MAX_SES_FIELD_LENGTH): string => {
    const cleaned = value
        .replace(/[\u0000-\u001f\u007f]/g, ' ')
        .replace(/\[/g, '(')
        .replace(/\]/g, ')')
    return cleaned.length > max ? cleaned.slice(0, max) + '…' : cleaned
}

/**
 * Format log lines for a single SES event record.
 *
 * Recipient-keyed events (Delivery, Bounce, Complaint) emit one line per actual recipient
 * reported by SES. Account-scoped events (Open, Click, RenderingFailure, Reject) emit a
 * single line. Open/Click don't carry per-recipient info in the SES payload, so fanning
 * out over `mail.destination` would fabricate claims about recipients who didn't engage.
 * Send events are skipped since the send is already logged when the email is dispatched.
 */
// Truncate a per-recipient fan-out list so we never emit more than
// `MAX_RECIPIENTS_PER_EVENT` log lines per SES record. When truncation fires, append
// a summary line so operators can see something was dropped. The caller still gets
// the full recipient list for opt-out and metric processing.
const truncateWithSummary = <T>(
    items: T[],
    format: (item: T) => SesEventLogLine,
    summaryLevel: SesEventLogLine['level'],
    summaryTimestamp: string
): SesEventLogLine[] => {
    if (items.length <= MAX_RECIPIENTS_PER_EVENT) {
        return items.map(format)
    }
    const truncated = items.slice(0, MAX_RECIPIENTS_PER_EVENT).map(format)
    const omitted = items.length - MAX_RECIPIENTS_PER_EVENT
    truncated.push({
        level: summaryLevel,
        message: `... and ${omitted} more recipient${omitted === 1 ? '' : 's'} omitted from logs`,
        timestamp: summaryTimestamp,
    })
    return truncated
}

export const formatSesEventLogs = (rec: SesEventRecord): SesEventLogLine[] => {
    switch (rec.eventType) {
        case 'Delivery': {
            const smtp = rec.delivery.smtpResponse ? `, ${sanitizeSesField(rec.delivery.smtpResponse)}` : ''
            const parts: string[] = []
            if (rec.delivery.processingTimeMillis !== undefined) {
                parts.push(`${rec.delivery.processingTimeMillis}ms`)
            }
            if (rec.delivery.reportingMTA) {
                parts.push(`reporting MTA ${sanitizeSesField(rec.delivery.reportingMTA)}`)
            }
            const suffix = parts.length ? ` (${parts.join(', ')})` : ''
            // Only emit per-recipient lines when SES names the successful recipients. Falling
            // back to `mail.destination` would misreport failed addresses as "Delivered".
            if (!rec.delivery.recipients || rec.delivery.recipients.length === 0) {
                return [{ level: 'info', message: `Delivered${smtp}${suffix}`, timestamp: rec.delivery.timestamp }]
            }
            return truncateWithSummary(
                rec.delivery.recipients,
                (recipient) => ({
                    level: 'info',
                    message: `Delivered to ${sanitizeSesField(recipient)}${smtp}${suffix}`,
                    timestamp: rec.delivery.timestamp,
                }),
                'info',
                rec.delivery.timestamp
            )
        }
        case 'Bounce': {
            const bounceType = rec.bounce.bounceType
            const level: SesEventLogLine['level'] = bounceType === 'Permanent' ? 'error' : 'warn'
            return truncateWithSummary(
                rec.bounce.bouncedRecipients,
                (r) => {
                    const diag = r.diagnosticCode ? sanitizeSesField(r.diagnosticCode) : ''
                    // SES typically inlines the SMTP status inside diagnosticCode already
                    // (e.g. "smtp; 550 5.1.1 user unknown"). Only append status separately
                    // when the diagnostic doesn't already contain it, to avoid duplicates like
                    // "... user unknown (5.1.1) (5.1.1)".
                    const statusSuffix = r.status && !diag.includes(r.status) ? ` (${sanitizeSesField(r.status)})` : ''
                    const diagPart = diag ? `, ${diag}` : ''
                    return {
                        level,
                        message: `${bounceType} bounce to ${sanitizeSesField(r.emailAddress)}${diagPart}${statusSuffix}`,
                        timestamp: rec.bounce.timestamp,
                    }
                },
                level,
                rec.bounce.timestamp
            )
        }
        case 'Complaint': {
            const feedback = rec.complaint.complaintFeedbackType
                ? `, feedback type: ${sanitizeSesField(rec.complaint.complaintFeedbackType)}`
                : ''
            return truncateWithSummary(
                rec.complaint.complainedRecipients,
                (r) => ({
                    level: 'warn',
                    message: `Complaint from ${sanitizeSesField(r.emailAddress)}${feedback}`,
                    timestamp: rec.complaint.timestamp,
                }),
                'warn',
                rec.complaint.timestamp
            )
        }
        case 'Open': {
            // SES Open events don't identify which recipient opened - the event applies to
            // whoever fetched the tracking pixel. Emit one account-scoped line; the row
            // timestamp conveys "when".
            // The message intentionally omits the word "Email" since the [Action:…] rich
            // token in front of it renders as the action's name (typically "Email"), so
            // "Email Email opened" would be redundant in the workflow logs viewer.
            const ua = rec.open.userAgent ? ` (${sanitizeSesField(rec.open.userAgent)})` : ''
            return [{ level: 'info', message: `Opened${ua}`, timestamp: rec.open.timestamp }]
        }
        case 'Click': {
            const ua = rec.click.userAgent ? ` (${sanitizeSesField(rec.click.userAgent)})` : ''
            return [
                {
                    level: 'info',
                    message: `Link clicked: ${sanitizeSesField(rec.click.link)}${ua}`,
                    timestamp: rec.click.timestamp,
                },
            ]
        }
        case 'RenderingFailure': {
            const tmpl = rec.renderingFailure.templateName
                ? ` for template ${sanitizeSesField(rec.renderingFailure.templateName)}`
                : ''
            return [
                {
                    level: 'error',
                    message: `Rendering failure${tmpl}: ${sanitizeSesField(rec.renderingFailure.errorMessage)}`,
                    timestamp: rec.mail.timestamp,
                },
            ]
        }
        case 'Reject': {
            const reason = rec.reject?.reason ? `: ${sanitizeSesField(rec.reject.reason)}` : ''
            return [
                {
                    level: 'error',
                    message: `Message rejected by SES${reason}`,
                    timestamp: rec.mail.timestamp,
                },
            ]
        }
        default:
            return []
    }
}

export class SesWebhookHandler {
    certCache: Record<string, Promise<string> | undefined> = {}

    private async fetchText(url: string): Promise<string> {
        const response = await fetch(url)
        if (response.status >= 400) {
            throw new Error(`Failed to fetch ${url}: ${response.status}`)
        }
        return await response.text()
    }

    private async fetchCert(url: string): Promise<string> {
        // Validate that the URL is from AWS SNS
        if (!this.isValidSnsCertUrl(url)) {
            throw new Error(`Invalid SNS certificate URL: ${url}`)
        }

        if (this.certCache[url]) {
            return await this.certCache[url]!
        }
        this.certCache[url] = this.fetchText(url)
        return this.certCache[url]!
    }

    private isValidSnsCertUrl(url: string): boolean {
        try {
            const parsedUrl = new URL(url)

            // Must be HTTPS
            if (parsedUrl.protocol !== 'https:') {
                return false
            }

            // Must be from sns.{region}.amazonaws.com
            const hostname = parsedUrl.hostname
            if (!hostname.match(/^sns\.[a-z0-9-]+\.amazonaws\.com$/)) {
                return false
            }

            // Must end with .pem
            if (!parsedUrl.pathname.endsWith('.pem')) {
                return false
            }

            return true
        } catch {
            return false
        }
    }

    private isValidSnsSubscribeUrl(url: string): boolean {
        try {
            const parsedUrl = new URL(url)

            if (parsedUrl.protocol !== 'https:') {
                return false
            }

            // Must be from sns.{region}.amazonaws.com
            if (!parsedUrl.hostname.match(/^sns\.[a-z0-9-]+\.amazonaws\.com$/)) {
                return false
            }

            return true
        } catch {
            return false
        }
    }

    /**
     * Parse incoming body accounting for SNS raw vs envelope
     */
    private parseIncomingBody(
        body: unknown
    ):
        | { mode: 'raw' | 'sns'; records: SesEventRecord[] }
        | { mode: 'sns'; envelope: SnsEnvelope; records?: SesEventRecord[] } {
        // If it's already an object with "Type", it's probably the SNS envelope (raw=false)
        if (body && typeof body === 'object' && 'Type' in (body as any)) {
            const env = SnsEnvelopeSchema.parse(body)
            if (env.Type === 'Notification') {
                const inner = parseJSON(env.Message)
                const record = SesEventRecordSchema.parse(inner)
                return { mode: 'sns', envelope: env, records: [record] }
            }
            // For non-Notification, return envelope; caller decides how to handle
            return { mode: 'sns', envelope: env }
        }

        // raw_message_delivery=true → body is already the SES array
        const records = SesEventBatchSchema.parse(body)
        return { mode: 'raw', records }
    }

    /**
     * Verify SNS signature
     * Best practice: verify the signature unless you're behind a trusted ALB / private VPC.
     */
    private async verifySnsSignature(envelope: SnsEnvelope): Promise<boolean> {
        try {
            // 1) Fetch cert
            const cert = await this.fetchCert(envelope.SigningCertURL)
            // 2) Build string to sign (per SNS docs)
            const stringToSign = this.buildStringToSign(envelope)
            // 3) Verify
            const verifier = crypto.createVerify('RSA-SHA1') // SNS SignatureVersion=1 uses SHA1
            verifier.update(stringToSign, 'utf8')
            return verifier.verify(cert, envelope.Signature, 'base64')
        } catch {
            return false
        }
    }

    /**
     * Build string to sign for SNS signature verification
     */
    private buildStringToSign(m: SnsEnvelope): string {
        // Follows AWS SNS docs for SignatureVersion=1
        // For Notification:
        //   "Message\n{Message}\nMessageId\n{MessageId}\nSubject\n{Subject}\nTimestamp\n{Timestamp}\nTopicArn\n{TopicArn}\nType\n{Type}\n"
        // Subject line omitted if not present.
        const lines: string[] = []
        const pushKV = (k: string, v?: string) => {
            if (v !== undefined) {
                lines.push(k)
                lines.push(v)
            }
        }
        if (m.Type === 'Notification') {
            pushKV('Message', m.Message)
            pushKV('MessageId', m.MessageId)
            pushKV('Subject', m.Subject)
            pushKV('Timestamp', m.Timestamp)
            pushKV('TopicArn', m.TopicArn)
            pushKV('Type', m.Type)
        } else if (m.Type === 'SubscriptionConfirmation' || m.Type === 'UnsubscribeConfirmation') {
            pushKV('Message', m.Message)
            pushKV('MessageId', m.MessageId)
            pushKV('SubscribeURL', (m as any).SubscribeURL) // present in confirmation payload body, not in envelope schema
            pushKV('Timestamp', m.Timestamp)
            pushKV('Token', m.Token!)
            pushKV('TopicArn', m.TopicArn)
            pushKV('Type', m.Type)
        }
        return lines.join('\n') + '\n'
    }

    async handleWebhook(opts: {
        body: any
        headers: Record<string, string | string[] | undefined>
        verifySignature?: boolean
    }): Promise<{
        status: number
        body: unknown
        metrics?: {
            functionId?: string
            invocationId?: string
            actionId?: string
            metricName: MinimalAppMetric['metric_name']
        }[]
        logEntries?: {
            functionId?: string
            invocationId?: string
            actionId?: string
            teamId?: string
            level: SesEventLogLine['level']
            message: string
            timestamp: string
        }[]
        optOutRecipients?: {
            teamId?: string
            emailAddresses: string[]
        }[]
    }> {
        logger.info('[SesWebhookHandler] handleWebhook', { body: opts.body, headers: opts.headers })
        const parsed = this.parseIncomingBody(opts.body)

        logger.info('[SesWebhookHandler] parsed', { parsed })

        // If SNS envelope present and verification requested, verify signature
        if ('envelope' in parsed && opts.verifySignature) {
            logger.info('[SesWebhookHandler] verifying signature', { envelope: parsed.envelope })
            const ok = await this.verifySnsSignature(parsed.envelope)
            logger.info('[SesWebhookHandler] signature verified', { ok })
            if (!ok) {
                return { status: 403, body: { error: 'Invalid SNS signature' } }
            }
        }

        // Handle confirmation flow
        if (parsed.mode === 'sns' && 'envelope' in parsed && parsed.envelope?.Type === 'SubscriptionConfirmation') {
            logger.info('[SesWebhookHandler] confirming subscription', { envelope: parsed.envelope })
            // Confirm by visiting SubscribeURL (contained in the *message JSON*, not envelope.Message field here)
            // We need to fetch the inner message JSON to get SubscribeURL
            const env = parsed.envelope
            const inner = parseJSON(env.Message) as { SubscribeURL?: string }
            logger.info('[SesWebhookHandler] confirming subscription', { inner })
            if (inner.SubscribeURL) {
                if (!this.isValidSnsSubscribeUrl(inner.SubscribeURL)) {
                    logger.warn('[SesWebhookHandler] Invalid SubscribeURL, rejecting', {
                        url: inner.SubscribeURL,
                    })
                    return { status: 403, body: { error: 'Invalid SubscribeURL' } }
                }
                await this.fetchText(inner.SubscribeURL)
            }
            return { status: 200, body: { ok: true } }
        }

        if (parsed.mode === 'sns' && 'envelope' in parsed && parsed.envelope?.Type === 'UnsubscribeConfirmation') {
            logger.info('[SesWebhookHandler] confirming unsubscribe', { envelope: parsed.envelope })
            return { status: 200, body: { ok: true } }
        }

        // Process SES events
        const records = parsed.mode === 'raw' ? parsed.records : parsed.records!
        const metrics: {
            functionId?: string
            invocationId?: string
            actionId?: string
            metricName: MinimalAppMetric['metric_name']
        }[] = []
        const logEntries: {
            functionId?: string
            invocationId?: string
            actionId?: string
            teamId?: string
            level: SesEventLogLine['level']
            message: string
            timestamp: string
        }[] = []
        const optOutRecipients: {
            teamId?: string
            emailAddresses: string[]
        }[] = []

        for (const rec of records) {
            logger.info('[SesWebhookHandler] processing record', { rec })
            const tags = rec.mail.tags
            const { functionId, invocationId, teamId, actionId } = parseEmailTrackingCode(tags?.ph_id?.[0] || '') || {}

            if (!functionId && !invocationId) {
                logger.error('[SesWebhookHandler] handleWebhook: No functionId or invocationId found', { rec })
                continue
            }

            const metricName = EVENT_TYPE_TO_METRIC_NAME[rec.eventType]
            if (metricName) {
                metrics.push({ functionId, invocationId, actionId, metricName })
            }

            // Only trust the actionId for the rich-log prefix if it matches the allowlist
            // the frontend log viewer uses for Action tokens. `actionId` originates from the
            // attacker-influenceable `ph_id` tag, so without this gate a crafted payload
            // could close the token early (e.g. `act] [Actor:victim`) and inject fake rich
            // tokens into the workflow log viewer. Real action ids are UUID/slug-shaped.
            const safeActionId = actionId && /^[a-zA-Z0-9_-]+$/.test(actionId) ? actionId : undefined
            for (const line of formatSesEventLogs(rec)) {
                // Prefix with [Action:<id>] so the workflow logs viewer can correlate
                // the line with the email step and its per-step log filter picks it up.
                const prefix = safeActionId ? `[Action:${safeActionId}] ` : ''
                logEntries.push({
                    functionId,
                    invocationId,
                    actionId,
                    teamId,
                    level: line.level,
                    message: `${prefix}${line.message}`,
                    timestamp: line.timestamp,
                })
            }

            // Opt out recipients on permanent bounces
            if (teamId && rec.eventType === 'Bounce' && rec.bounce.bounceType === 'Permanent') {
                const emails = rec.bounce.bouncedRecipients.map((r) => r.emailAddress)
                optOutRecipients.push({ teamId, emailAddresses: emails })
            }
        }

        return { status: 200, body: { ok: true }, metrics, logEntries, optOutRecipients }
    }
}
