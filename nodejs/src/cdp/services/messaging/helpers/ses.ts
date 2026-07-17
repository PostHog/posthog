import crypto from 'node:crypto'
import { z } from 'zod'

import { MinimalAppMetric } from '~/cdp/types'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { fetch } from '~/common/utils/request'

import { EmailTrackingCodeSigner, TRACKING_CODE_HEADER_NAME, trackingCodeFormatCounter } from './tracking-code'

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
    commonHeaders: z.object({ subject: z.string().optional() }).passthrough().optional(),
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

// Acknowledged so SNS doesn't retry forever; details aren't surfaced.
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
    level: 'warn' | 'error'
    message: string
}

const MAX_SES_FIELD_LENGTH = 1024

// Strip control chars, neutralize rich-log bracket tokens, and cap length.
const sanitizeSesField = (value: string, max = MAX_SES_FIELD_LENGTH): string => {
    const cleaned = value
        .replace(/[\u0000-\u001f\u007f]/g, ' ')
        .replace(/\[/g, '(')
        .replace(/\]/g, ')')
    return cleaned.length > max ? cleaned.slice(0, max) + '…' : cleaned
}

// Only warn/error events become log entries. Info-level events (Send, Delivery, Open, Click)
// are tracked as metrics only - they're analytics signal, not debugging signal.
export const formatSesEventLogs = (rec: SesEventRecord): SesEventLogLine[] => {
    switch (rec.eventType) {
        case 'Bounce': {
            const bounceType = rec.bounce.bounceType
            const level: SesEventLogLine['level'] = bounceType === 'Permanent' ? 'error' : 'warn'
            return rec.bounce.bouncedRecipients.map((r) => {
                const diag = r.diagnosticCode ? sanitizeSesField(r.diagnosticCode) : ''
                // SES typically inlines the SMTP status inside diagnosticCode already
                // (e.g. "smtp; 550 5.1.1 user unknown"), so skip the suffix when present.
                const statusSuffix = r.status && !diag.includes(r.status) ? ` (${sanitizeSesField(r.status)})` : ''
                const diagPart = diag ? `, ${diag}` : ''
                return {
                    level,
                    message: `${bounceType} bounce to ${sanitizeSesField(r.emailAddress)}${diagPart}${statusSuffix}`,
                }
            })
        }
        case 'Complaint': {
            const feedback = rec.complaint.complaintFeedbackType
                ? `, feedback type: ${sanitizeSesField(rec.complaint.complaintFeedbackType)}`
                : ''
            return rec.complaint.complainedRecipients.map((r) => ({
                level: 'warn',
                message: `Complaint from ${sanitizeSesField(r.emailAddress)}${feedback}`,
            }))
        }
        case 'RenderingFailure': {
            const tmpl = rec.renderingFailure.templateName
                ? ` for template ${sanitizeSesField(rec.renderingFailure.templateName)}`
                : ''
            return [
                {
                    level: 'error',
                    message: `Rendering failure${tmpl}: ${sanitizeSesField(rec.renderingFailure.errorMessage)}`,
                },
            ]
        }
        case 'Reject': {
            const reason = rec.reject?.reason ? `: ${sanitizeSesField(rec.reject.reason)}` : ''
            return [
                {
                    level: 'error',
                    message: `Message rejected by SES${reason}`,
                },
            ]
        }
        default:
            return []
    }
}

export class SesWebhookHandler {
    certCache: Record<string, Promise<string> | undefined> = {}

    constructor(private trackingCodeSigner: EmailTrackingCodeSigner) {}

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
            parentRunId?: string
            distinctId?: string
            metricName: MinimalAppMetric['metric_name']
            properties?: Record<string, any>
            timestamp?: string
        }[]
        logEntries?: {
            functionId?: string
            invocationId?: string
            actionId?: string
            parentRunId?: string
            teamId?: string
            level: SesEventLogLine['level']
            message: string
        }[]
        optOutRecipients?: {
            teamId?: string
            emailAddresses: string[]
        }[]
    }> {
        logger.info('[SesWebhookHandler] handleWebhook', { body: opts.body, headers: opts.headers })
        const parsed = this.parseIncomingBody(opts.body)

        logger.info('[SesWebhookHandler] parsed', { parsed })

        // When verification is required the message must be a signed SNS envelope. Raw deliveries
        // carry no signature, and prod uses envelope delivery, so reject them to block forged events.
        if (opts.verifySignature) {
            if (!('envelope' in parsed)) {
                return { status: 403, body: { error: 'Unsigned raw delivery not allowed' } }
            }
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
            parentRunId?: string
            distinctId?: string
            metricName: MinimalAppMetric['metric_name']
            properties?: Record<string, any>
            timestamp?: string
        }[] = []
        const logEntries: {
            functionId?: string
            invocationId?: string
            actionId?: string
            parentRunId?: string
            teamId?: string
            level: SesEventLogLine['level']
            message: string
        }[] = []
        const optOutRecipients: {
            teamId?: string
            emailAddresses: string[]
        }[] = []

        for (const rec of records) {
            logger.info('[SesWebhookHandler] processing record', { rec })
            // Prefer the custom MIME header (carries the full signed code including distinct_id,
            // unbounded). Fall back to the SES EmailTag for messages sent before the header carrier
            // was added, or where the configuration set hasn't enabled `IncludeOriginalHeaders`.
            const headerValue = rec.mail.headers?.find(
                (h) => h.name.toLowerCase() === TRACKING_CODE_HEADER_NAME.toLowerCase()
            )?.value
            const tagValue = rec.mail.tags?.ph_id?.[0]
            const parsedCode = this.trackingCodeSigner.parse(headerValue ?? tagValue ?? '')
            if (parsedCode) {
                trackingCodeFormatCounter.inc({ format: parsedCode.format, source: 'ses' })
            }
            const { functionId, invocationId, teamId, actionId, parentRunId, distinctId, isTest } = parsedCode || {}

            if (!functionId && !invocationId) {
                logger.error('[SesWebhookHandler] handleWebhook: No functionId or invocationId found', { rec })
                continue
            }

            const metricName = EVENT_TYPE_TO_METRIC_NAME[rec.eventType]
            // Test sends (from the editor's "Run test") are not production activity, so we skip
            // their delivery/open/click metrics — otherwise a draft/never-enabled workflow shows
            // email activity in its Metrics tab. Bounce-driven opt-outs below still apply.
            if (metricName && !isTest) {
                const properties: Record<string, any> = {
                    $email_to: rec.mail.destination?.[0],
                    $email_subject: rec.mail.commonHeaders?.subject,
                }

                // Each SES event detail carries its own timestamp (open.timestamp, click.timestamp, etc.)
                // — prefer those over the webhook receipt time so the event reflects when the action
                // actually happened, not when AWS got around to delivering the notification.
                let timestamp: string | undefined
                if ('open' in rec && rec.open) {
                    timestamp = rec.open.timestamp
                } else if ('click' in rec && rec.click) {
                    timestamp = rec.click.timestamp
                    properties.$link_url = rec.click.link
                } else if ('delivery' in rec && rec.delivery) {
                    timestamp = rec.delivery.timestamp
                } else if ('bounce' in rec && rec.bounce) {
                    timestamp = rec.bounce.timestamp
                } else if ('complaint' in rec && rec.complaint) {
                    timestamp = rec.complaint.timestamp
                }
                timestamp = timestamp ?? rec.mail.timestamp

                metrics.push({
                    functionId,
                    invocationId,
                    actionId,
                    parentRunId,
                    distinctId,
                    metricName,
                    properties,
                    timestamp,
                })
            }

            // Allowlist actionId before interpolating into the [Action:…] rich-log token,
            // since actionId comes from the attacker-influenceable ph_id tag.
            const safeActionId = actionId && /^[a-zA-Z0-9_-]+$/.test(actionId) ? actionId : undefined
            // Skip test sends here too (mirrors the metrics gate above) so a "Run test" bounce
            // doesn't write a misleading failure into the workflow's invocation logs.
            for (const line of isTest ? [] : formatSesEventLogs(rec)) {
                const prefix = safeActionId ? `[Action:${safeActionId}] ` : ''
                logEntries.push({
                    functionId,
                    invocationId,
                    actionId,
                    parentRunId,
                    teamId,
                    level: line.level,
                    message: `${prefix}${line.message}`,
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
