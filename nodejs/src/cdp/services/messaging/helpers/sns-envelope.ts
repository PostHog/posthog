import { LRUCache } from 'lru-cache'
import crypto from 'node:crypto'
import { Counter } from 'prom-client'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { fetch } from '~/common/utils/request'

import { SesEventBatchSchema, SesEventRecord, SesEventRecordSchema, sanitizeSesField } from './ses-events'

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

export const parseSnsEnvelope = (raw: string): SnsEnvelope => SnsEnvelopeSchema.parse(parseJSON(raw))

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
    | { kind: 'records'; records: SesEventRecord[]; fromEnvelope: boolean; messageId?: string }
    | { kind: 'ack' }
    | { kind: 'reject'; status: number; error: string; certificateUnavailable?: boolean }

type ParsedBody = { mode: 'raw'; records: SesEventRecord[] } | { mode: 'sns'; envelope: SnsEnvelope }

export type SnsEnvelopeCheck =
    | Exclude<SnsEnvelopeVerdict, { kind: 'records' }>
    | { kind: 'accepted'; parsed: ParsedBody }

class SnsCertificateUnavailableError extends Error {}

const TRANSIENT_FETCH_STATUSES = new Set([408, 429])

class SnsFetchError extends Error {
    constructor(
        url: string,
        public status: number
    ) {
        super(`Failed to fetch ${url}: ${status}`)
    }
}

export const SNS_SIGNING_CERT_CACHE_SIZE = 32

const SNS_HOSTNAME = /^sns\.[a-z0-9-]+\.amazonaws\.com$/
const SNS_CERT_PATH = /^\/SimpleNotificationService-[A-Za-z0-9]{8,64}\.pem$/

const parseSnsUrl = (url: string): URL | undefined => {
    const parsed = URL.parse(url)
    return parsed?.protocol === 'https:' && SNS_HOSTNAME.test(parsed.hostname) ? parsed : undefined
}

const canonicalSnsCertUrl = (url: string): string | undefined => {
    const parsed = parseSnsUrl(url)
    return parsed && SNS_CERT_PATH.test(parsed.pathname) ? `https://${parsed.hostname}${parsed.pathname}` : undefined
}

export class SnsEnvelopeVerifier {
    private certCache = new LRUCache<string, string>({
        max: SNS_SIGNING_CERT_CACHE_SIZE,
        ignoreFetchAbort: true,
        fetchMethod: (url) => this.fetchText(url),
    })
    protected allowedTopicArns: Set<string>

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
            await response.dump().catch(() => undefined)
            throw new SnsFetchError(url, response.status)
        }
        return await response.text()
    }

    private async fetchCert(url: string): Promise<string> {
        const certUrl = canonicalSnsCertUrl(url)
        if (!certUrl) {
            throw new Error(`Invalid SNS certificate URL: ${url}`)
        }
        return await this.certCache.forceFetch(certUrl)
    }

    private parseIncomingBody(body: unknown): ParsedBody {
        if (body && typeof body === 'object' && 'Type' in (body as any)) {
            return { mode: 'sns', envelope: SnsEnvelopeSchema.parse(body) }
        }

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

    private async verifySnsSignature(envelope: SnsEnvelope): Promise<boolean> {
        if (!canonicalSnsCertUrl(envelope.SigningCertURL)) {
            return false
        }
        let cert: string
        try {
            cert = await this.fetchCert(envelope.SigningCertURL)
        } catch (error) {
            if (error instanceof SnsFetchError && error.status < 500 && !TRANSIENT_FETCH_STATUSES.has(error.status)) {
                return false
            }
            throw new SnsCertificateUnavailableError(String(error))
        }
        try {
            const stringToSign = this.buildStringToSign(envelope)
            const verifier = crypto.createVerify('RSA-SHA1') // SNS SignatureVersion=1 uses SHA1
            verifier.update(stringToSign, 'utf8')
            return verifier.verify(cert, envelope.Signature, 'base64')
        } catch {
            return false
        }
    }

    private buildStringToSign(m: SnsEnvelope): string {
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

    async verify(
        body: unknown,
        { verifySignature = true }: { verifySignature?: boolean } = {}
    ): Promise<SnsEnvelopeVerdict> {
        const check = await this.verifyEnvelope(body, { verifySignature })
        if (check.kind !== 'accepted') {
            return check
        }
        const { parsed } = check
        if (parsed.mode === 'raw') {
            return { kind: 'records', records: parsed.records, fromEnvelope: false }
        }
        return {
            kind: 'records',
            records: this.parseNotificationRecords(parsed.envelope),
            fromEnvelope: true,
            messageId: parsed.envelope.MessageId,
        }
    }

    protected async verifyEnvelope(
        body: unknown,
        { verifySignature }: { verifySignature: boolean }
    ): Promise<SnsEnvelopeCheck> {
        const parsed = this.parseIncomingBody(body)
        logger.info('[SnsEnvelopeVerifier] verify', { mode: parsed.mode })

        // When verification is required the message must be a signed SNS envelope. Raw deliveries
        // carry no signature, and prod uses envelope delivery, so reject them to block forged events.
        if (verifySignature && !('envelope' in parsed)) {
            return { kind: 'reject', status: 403, error: 'Unsigned raw delivery not allowed' }
        }

        // A valid signature proves the envelope came from AWS, but not from the workflow SES topic.
        if ('envelope' in parsed && !this.isTopicAllowed(parsed.envelope.TopicArn)) {
            logger.warn('[SnsEnvelopeVerifier] Rejecting event from disallowed TopicArn', {
                topicArn: parsed.envelope.TopicArn,
            })
            return { kind: 'reject', status: 403, error: 'SNS TopicArn not allowed' }
        }

        if (verifySignature && 'envelope' in parsed) {
            logger.info('[SnsEnvelopeVerifier] verifying signature', {
                type: parsed.envelope.Type,
                messageId: parsed.envelope.MessageId,
            })
            let ok: boolean
            try {
                ok = await this.verifySnsSignature(parsed.envelope)
            } catch (error) {
                if (!(error instanceof SnsCertificateUnavailableError)) {
                    throw error
                }
                logger.warn('[SnsEnvelopeVerifier] signing certificate unavailable', { error: error.message })
                return { kind: 'reject', status: 403, error: 'Invalid SNS signature', certificateUnavailable: true }
            }
            logger.info('[SnsEnvelopeVerifier] signature verified', { ok })
            if (!ok) {
                return { kind: 'reject', status: 403, error: 'Invalid SNS signature' }
            }
        }

        if (parsed.mode === 'sns' && parsed.envelope.Type === 'SubscriptionConfirmation') {
            logger.info('[SnsEnvelopeVerifier] confirming subscription', { envelope: parsed.envelope })
            const subscribeUrl = parsed.envelope.SubscribeURL
            if (subscribeUrl) {
                if (!parseSnsUrl(subscribeUrl)) {
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

        return { kind: 'accepted', parsed }
    }
}
