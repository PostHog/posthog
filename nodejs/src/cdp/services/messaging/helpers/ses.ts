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
    tags: z.record(z.array(z.string())).optional(), // your message tags: { user_id: ["u_123"] }
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
const SesRejectEventSchema = SesCommonEventBase.extend({ eventType: z.literal('Reject') })

const SesEventRecordSchema = z.union([
    SesOpenEventSchema,
    SesClickEventSchema,
    SesDeliveryEventSchema,
    SesBounceEventSchema,
    SesComplaintEventSchema,
    SesRenderingFailureSchema,
    SesSendEventSchema,
    SesRejectEventSchema,
])

const SesEventBatchSchema = z.array(SesEventRecordSchema)

export type SesEventRecord = z.infer<typeof SesEventRecordSchema>

const EVENT_TYPE_TO_METRIC_NAME: Record<SesEventRecord['eventType'], MinimalAppMetric['metric_name']> = {
    Open: 'email_opened',
    Click: 'email_link_clicked',
    // Delivery: 'email_sent',
    Bounce: 'email_bounced',
    Complaint: 'email_blocked',
    RenderingFailure: 'email_failed',
    Send: 'email_sent',
    Reject: 'email_failed',
    Delivery: 'email_sent',
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
            metricName: MinimalAppMetric['metric_name']
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
            metricName: MinimalAppMetric['metric_name']
        }[] = []

        for (const rec of records) {
            logger.info('[SesWebhookHandler] processing record', { rec })
            const tags = rec.mail.tags
            const { functionId, invocationId } = parseEmailTrackingCode(tags?.ph_id?.[0] || '') || {}

            if (!functionId && !invocationId) {
                logger.error('[SesWebhookHandler] handleWebhook: No functionId or invocationId found', { rec })
                continue
            }

            const metricName = EVENT_TYPE_TO_METRIC_NAME[rec.eventType]
            metrics.push({ functionId, invocationId, metricName })
        }

        return { status: 200, body: { ok: true }, metrics }
    }
}
