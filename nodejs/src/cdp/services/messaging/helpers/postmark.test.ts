import {
    POSTMARK_METADATA_VALUE_LIMIT,
    PostmarkWebhookHandler,
    buildPostmarkMetadataHeaders,
    reassemblePostmarkMetadataCode,
} from './postmark'
import { EmailTrackingCodeSigner } from './tracking-code'

const signer = new EmailTrackingCodeSigner('test-signing-key', 'http://tracking.local')

const generateCode = (overrides: { distinctId?: string; isTest?: boolean } = {}): string =>
    signer.generate(
        {
            functionId: 'fn-1',
            id: 'inv-1',
            teamId: 2,
            parentRunId: 'run-1',
            state: { actionId: 'action_email_1' },
            distinctId: overrides.distinctId,
        } as any,
        { isTest: overrides.isTest, directTracking: true }
    )

// Webhook payloads carry the metadata keys without the X-PM-Metadata- header prefix
const toWebhookMetadata = (headers: Record<string, string>): Record<string, string> =>
    Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.replace(/^X-PM-Metadata-/, ''), value]))

describe('postmark metadata chunking', () => {
    it('round-trips a signed code through chunked headers, splitting at the 80-char field limit', () => {
        // A long distinctId forces multiple chunks — the shape real batch-flow codes have
        const code = generateCode({ distinctId: 'user:with:colons:' + 'x'.repeat(150) })
        const headers = buildPostmarkMetadataHeaders(code)!
        expect(Object.keys(headers).length).toBeGreaterThan(1)
        for (const value of Object.values(headers)) {
            expect(value.length).toBeLessThanOrEqual(POSTMARK_METADATA_VALUE_LIMIT)
        }
        expect(reassemblePostmarkMetadataCode(toWebhookMetadata(headers))).toBe(code)
    })

    it('reassembles chunks in numeric order regardless of key order', () => {
        // A lexicographic sort would put posthog-10 before posthog-2 and corrupt every long code
        const metadata: Record<string, string> = {}
        const parts = ['AA', 'BB', 'CC', 'DD', 'EE', 'FF', 'GG', 'HH', 'II', 'JJ']
        for (const index of [10, 1, 9, 2, 8, 3, 7, 4, 6, 5]) {
            metadata[`posthog-${index}`] = parts[index - 1]
        }
        expect(reassemblePostmarkMetadataCode(metadata)).toBe(parts.join(''))
    })

    it('refuses codes that cannot fit the 10-field cap instead of truncating', () => {
        expect(buildPostmarkMetadataHeaders('x'.repeat(10 * POSTMARK_METADATA_VALUE_LIMIT + 1))).toBeNull()
    })
})

describe('webhook URL token', () => {
    it('is scoped to one integration, so a token minted for another sender is rejected', () => {
        const token = signer.webhookToken(123)
        expect(signer.verifyWebhookToken(123, token)).toBe(true)
        expect(signer.verifyWebhookToken(124, token)).toBe(false)
        expect(signer.verifyWebhookToken(123, 'forged')).toBe(false)
    })
})

describe('PostmarkWebhookHandler', () => {
    const handler = new PostmarkWebhookHandler(signer)
    const metadataFor = (code: string): Record<string, string> => toWebhookMetadata(buildPostmarkMetadataHeaders(code)!)

    it('records email_delivered from a Delivery event with a validly signed code', () => {
        const result = handler.handleWebhook({
            body: {
                RecordType: 'Delivery',
                Recipient: 'jane@example.com',
                DeliveredAt: '2026-08-20T10:00:00Z',
                Subject: 'Hello',
                Metadata: metadataFor(generateCode({ distinctId: 'user-1' })),
            },
        })
        expect(result.status).toBe(200)
        expect(result.metrics).toEqual([
            expect.objectContaining({
                functionId: 'fn-1',
                invocationId: 'inv-1',
                distinctId: 'user-1',
                metricName: 'email_delivered',
                timestamp: '2026-08-20T10:00:00Z',
            }),
        ])
    })

    it('records email_bounced, logs a warning, and opts the recipient out on a hard bounce', () => {
        const result = handler.handleWebhook({
            body: {
                RecordType: 'Bounce',
                Type: 'HardBounce',
                Email: 'gone@example.com',
                Description: 'The server was unable to deliver your message',
                BouncedAt: '2026-08-20T10:01:00Z',
                Metadata: metadataFor(generateCode()),
            },
        })
        expect(result.metrics).toEqual([expect.objectContaining({ metricName: 'email_bounced' })])
        expect(result.logEntries).toEqual([
            expect.objectContaining({ level: 'warn', message: expect.stringContaining('HardBounce') }),
        ])
        expect(result.optOutRecipients).toEqual([{ teamId: '2', emailAddresses: ['gone@example.com'] }])
    })

    it('records email_blocked from a spam complaint', () => {
        const result = handler.handleWebhook({
            body: { RecordType: 'SpamComplaint', Email: 'a@b.com', Metadata: metadataFor(generateCode()) },
        })
        expect(result.metrics).toEqual([expect.objectContaining({ metricName: 'email_blocked' })])
    })

    it('skips metrics and logs for test sends but still opts out on a hard bounce', () => {
        const result = handler.handleWebhook({
            body: {
                RecordType: 'Bounce',
                Type: 'HardBounce',
                Email: 'gone@example.com',
                Metadata: metadataFor(generateCode({ isTest: true })),
            },
        })
        expect(result.metrics).toEqual([])
        expect(result.logEntries).toEqual([])
        expect(result.optOutRecipients).toEqual([{ teamId: '2', emailAddresses: ['gone@example.com'] }])
    })

    it('rejects a tampered tracking code so forged payloads cannot inject metrics', () => {
        const code = generateCode()
        const tampered = code.slice(0, -2) + (code.endsWith('AA') ? 'BB' : 'AA')
        const result = handler.handleWebhook({
            body: { RecordType: 'Delivery', Metadata: metadataFor(tampered) },
        })
        expect(result.status).toBe(403)
        expect(result.metrics).toBeUndefined()
    })

    it.each([
        ['events without PostHog metadata (mail we did not send)', { RecordType: 'Delivery', Recipient: 'x@y.com' }],
        [
            'record types we record ourselves or do not map',
            { RecordType: 'Open', Metadata: { 'posthog-1': 'irrelevant' } },
        ],
    ])('acknowledges but ignores %s', (_name, body) => {
        const result = handler.handleWebhook({ body })
        expect(result.status).toBe(200)
        expect(result.metrics ?? []).toEqual([])
    })
})
