import crypto from 'node:crypto'
import { Counter } from 'prom-client'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { fetch } from '~/common/utils/request'

import { SesEventBatchSchema, SesEventRecord, SesEventRecordSchema, sanitizeSesField } from './ses-events'

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
    Message: z.string(), // either SES event JSON (Notification) or human-readable confirmation text
    // Top-level on (Un)SubscribeConfirmation payloads and part of their signed string, so it must
    // survive schema parsing for signature verification to succeed.
    SubscribeURL: z.string().optional(),
    Timestamp: z.string(),
    SignatureVersion: z.enum(['1']),
    Signature: z.string(),
    SigningCertURL: z.string().url(),
    UnsubscribeURL: z.string().url().optional(),
})

export type SnsEnvelope = z.infer<typeof SnsEnvelopeSchema>

// Kept off `email_tracking_errors_total` because the SES webhook errors alert sums that counter, and an
// SNS message that is not an SES event is acknowledged, not a fault.
const sesIgnoredNotificationsCounter = new Counter({
    name: 'ses_webhook_ignored_notifications_total',
    help: 'SNS notifications on the SES webhook acknowledged without processing',
    labelNames: ['reason'],
})

// Only text that does not open like JSON is quoted, because a malformed SES event carries recipients.
// Any AWS account can send it when the topic allowlist is empty, so it is sanitized like other SES fields.
const plainTextPrefix = (message: string): string | undefined =>
    /^\s*[{[]/.test(message) ? undefined : sanitizeSesField(message, 200)

export type SnsEnvelopeVerdict =
    | { kind: 'records'; records: SesEventRecord[]; fromEnvelope: boolean }
    | { kind: 'ack' }
    | { kind: 'reject'; status: number; error: string }

export class SnsEnvelopeVerifier {
    certCache: Record<string, Promise<string> | undefined> = {}
    protected allowedTopicArns: Set<string>

    // An empty allowlist accepts every topic.
    constructor(allowedTopicArns: string[] = []) {
        this.allowedTopicArns = new Set(allowedTopicArns.map((arn) => arn.trim()).filter(Boolean))
    }

    private isTopicAllowed(topicArn: string | undefined): boolean {
        if (this.allowedTopicArns.size === 0) {
            return true
        }
        return typeof topicArn === 'string' && this.allowedTopicArns.has(topicArn)
    }

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
        this.certCache[url] = this.fetchText(url).catch((error) => {
            delete this.certCache[url]
            throw error
        })
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
    ): { mode: 'raw'; records: SesEventRecord[] } | { mode: 'sns'; envelope: SnsEnvelope } {
        // If it's already an object with "Type", it's probably the SNS envelope (raw=false)
        if (body && typeof body === 'object' && 'Type' in (body as any)) {
            return { mode: 'sns', envelope: SnsEnvelopeSchema.parse(body) }
        }

        // raw_message_delivery=true → body is already the SES array
        const records = SesEventBatchSchema.parse(body)
        return { mode: 'raw', records }
    }

    private parseNotificationRecords(envelope: SnsEnvelope): SesEventRecord[] {
        let message: unknown
        try {
            message = parseJSON(envelope.Message)
        } catch {
            sesIgnoredNotificationsCounter.inc({ reason: 'non_json_message' })
            logger.warn('[SnsEnvelopeVerifier] Ignoring Notification whose Message is not JSON', {
                topicArn: envelope.TopicArn,
                messageId: envelope.MessageId,
                messageLength: envelope.Message.length,
                messagePrefix: plainTextPrefix(envelope.Message),
            })
            return []
        }
        return [SesEventRecordSchema.parse(message)]
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
            pushKV('SubscribeURL', m.SubscribeURL)
            pushKV('Timestamp', m.Timestamp)
            pushKV('Token', m.Token!)
            pushKV('TopicArn', m.TopicArn)
            pushKV('Type', m.Type)
        }
        return lines.join('\n') + '\n'
    }

    // Throws when the body is neither an SNS envelope nor an SES record batch.
    async verify(
        body: unknown,
        { verifySignature = true }: { verifySignature?: boolean } = {}
    ): Promise<SnsEnvelopeVerdict> {
        const parsed = this.parseIncomingBody(body)
        logger.info('[SnsEnvelopeVerifier] verify', { mode: parsed.mode })

        // When verification is required the message must be a signed SNS envelope. Raw deliveries
        // carry no signature, and prod uses envelope delivery, so reject them to block forged events.
        if (verifySignature) {
            if (!('envelope' in parsed)) {
                return { kind: 'reject', status: 403, error: 'Unsigned raw delivery not allowed' }
            }
            logger.info('[SnsEnvelopeVerifier] verifying signature', {
                type: parsed.envelope.Type,
                messageId: parsed.envelope.MessageId,
            })
            const ok = await this.verifySnsSignature(parsed.envelope)
            logger.info('[SnsEnvelopeVerifier] signature verified', { ok })
            if (!ok) {
                return { kind: 'reject', status: 403, error: 'Invalid SNS signature' }
            }
        }

        // Restrict accepted SNS envelopes (Notification, SubscriptionConfirmation, UnsubscribeConfirmation)
        // to the configured TopicArn allowlist. SNS signature verification proves the message came from
        // AWS, but not from a specific topic — this narrows accepted sources to the configured topics.
        if ('envelope' in parsed && !this.isTopicAllowed(parsed.envelope.TopicArn)) {
            logger.warn('[SnsEnvelopeVerifier] Rejecting event from disallowed TopicArn', {
                topicArn: parsed.envelope.TopicArn,
            })
            return { kind: 'reject', status: 403, error: 'SNS TopicArn not allowed' }
        }

        // Handle confirmation flow
        if (parsed.mode === 'sns' && parsed.envelope.Type === 'SubscriptionConfirmation') {
            logger.info('[SnsEnvelopeVerifier] confirming subscription', { envelope: parsed.envelope })
            // Confirm by visiting the top-level SubscribeURL field; Message is human-readable text here.
            const subscribeUrl = parsed.envelope.SubscribeURL
            if (subscribeUrl) {
                if (!this.isValidSnsSubscribeUrl(subscribeUrl)) {
                    logger.warn('[SnsEnvelopeVerifier] Invalid SubscribeURL, rejecting', {
                        url: subscribeUrl,
                    })
                    return { kind: 'reject', status: 403, error: 'Invalid SubscribeURL' }
                }
                await this.fetchText(subscribeUrl)
            } else {
                logger.warn('[SnsEnvelopeVerifier] SubscriptionConfirmation without SubscribeURL - cannot confirm')
                return { kind: 'reject', status: 400, error: 'Missing SubscribeURL' }
            }
            return { kind: 'ack' }
        }

        if (parsed.mode === 'sns' && parsed.envelope.Type === 'UnsubscribeConfirmation') {
            logger.info('[SnsEnvelopeVerifier] confirming unsubscribe', { envelope: parsed.envelope })
            return { kind: 'ack' }
        }

        const records = parsed.mode === 'raw' ? parsed.records : this.parseNotificationRecords(parsed.envelope)
        return { kind: 'records', records, fromEnvelope: parsed.mode === 'sns' }
    }
}
