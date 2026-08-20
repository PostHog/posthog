import {
    POSTMARK_METADATA_MAX_FIELDS,
    POSTMARK_METADATA_VALUE_LIMIT,
    PostmarkWebhookHandler,
    buildPostmarkMetadataHeaders,
    reassemblePostmarkMetadataCode,
} from './postmark'
import { EmailTrackingCodeSigner } from './tracking-code'

describe('postmark webhook helpers', () => {
    const signer = new EmailTrackingCodeSigner('00beef0000beef0000beef0000beef00', 'http://localhost:8010')

    const mintCode = (flags: { isTest?: boolean } = {}): string =>
        signer.generate(
            {
                functionId: 'c1a1e6c8-0000-4000-8000-000000000001',
                id: 'f3b2d4e0-0000-4000-8000-000000000002',
                teamId: 42,
                parentRunId: undefined,
                state: { actionId: 'action_1' } as any,
                distinctId: 'user@example.com',
            } as any,
            flags
        )

    const metadataFor = (code: string): Record<string, string> => {
        const headers = buildPostmarkMetadataHeaders(code)!
        // What Postmark echoes back: header names minus the X-PM-Metadata- prefix
        return Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.replace('X-PM-Metadata-', ''), v]))
    }

    describe('metadata chunking round-trip', () => {
        it.each([
            { name: 'short code, single chunk', length: 40, chunks: 1 },
            { name: 'boundary: exactly one chunk', length: POSTMARK_METADATA_VALUE_LIMIT, chunks: 1 },
            { name: 'one char over a chunk', length: POSTMARK_METADATA_VALUE_LIMIT + 1, chunks: 2 },
            {
                // 10 chunks exercises the numeric key sort: lexicographic order would put
                // "posthog-10" before "posthog-2" and corrupt the reassembled code
                name: 'max capacity: ten chunks',
                length: POSTMARK_METADATA_VALUE_LIMIT * POSTMARK_METADATA_MAX_FIELDS,
                chunks: 10,
            },
        ])('$name', ({ length, chunks }) => {
            const code = 'x'.repeat(length - 1) + 'Z'
            const headers = buildPostmarkMetadataHeaders(code)!
            expect(Object.keys(headers)).toHaveLength(chunks)
            // Shuffle key order to prove reassembly doesn't depend on object insertion order
            const metadata = Object.fromEntries(Object.entries(metadataFor(code)).reverse())
            expect(reassemblePostmarkMetadataCode(metadata)).toBe(code)
        })

        it('returns null when the code cannot fit even in ten fields', () => {
            expect(
                buildPostmarkMetadataHeaders(
                    'x'.repeat(POSTMARK_METADATA_VALUE_LIMIT * POSTMARK_METADATA_MAX_FIELDS + 1)
                )
            ).toBeNull()
        })

        it('a real signed tracking code fits and round-trips through metadata', () => {
            const code = mintCode()
            const reassembled = reassemblePostmarkMetadataCode(metadataFor(code))
            expect(reassembled).toBe(code)
            expect(signer.parse(reassembled!)?.invocationId).toBe('f3b2d4e0-0000-4000-8000-000000000002')
        })
    })

    describe('webhook URL token', () => {
        it('round-trips for the matching integration and rejects others', () => {
            const token = signer.webhookToken(123)
            expect(signer.verifyWebhookToken(123, token)).toBe(true)
            expect(signer.verifyWebhookToken(124, token)).toBe(false)
            expect(signer.verifyWebhookToken(123, 'forged')).toBe(false)
        })
    })

    describe('PostmarkWebhookHandler', () => {
        const handler = new PostmarkWebhookHandler(signer)

        const eventWith = (overrides: Record<string, any>, code = mintCode()): Record<string, any> => ({
            RecordType: 'Delivery',
            MessageID: '883953f4-6105-42a2-a16a-77a8eac79483',
            Recipient: 'john@example.com',
            DeliveredAt: '2026-08-20T16:33:54Z',
            Metadata: metadataFor(code),
            ...overrides,
        })

        it.each([
            { name: 'Delivery records email_delivered', overrides: {}, metric: 'email_delivered' },
            {
                name: 'Bounce records email_bounced',
                overrides: { RecordType: 'Bounce', Type: 'SoftBounce', Email: 'john@example.com' },
                metric: 'email_bounced',
            },
            {
                name: 'SpamComplaint records email_blocked (mirrors the SES Complaint mapping)',
                overrides: { RecordType: 'SpamComplaint', Email: 'john@example.com' },
                metric: 'email_blocked',
            },
        ])('$name', ({ overrides, metric }) => {
            const result = handler.handleWebhook({ body: eventWith(overrides) })
            expect(result.status).toBe(200)
            expect(result.metrics).toHaveLength(1)
            expect(result.metrics![0]).toMatchObject({
                metricName: metric,
                invocationId: 'f3b2d4e0-0000-4000-8000-000000000002',
                distinctId: 'user@example.com',
            })
        })

        it('a hard bounce opts the recipient out and writes a warn log', () => {
            const result = handler.handleWebhook({
                body: eventWith({
                    RecordType: 'Bounce',
                    Type: 'HardBounce',
                    // Bounce payloads carry Email, not the Delivery-only Recipient field
                    Recipient: undefined,
                    Email: 'gone@example.com',
                    Description: 'The server was unable to deliver your message',
                }),
            })
            expect(result.optOutRecipients).toEqual([{ teamId: '42', emailAddresses: ['gone@example.com'] }])
            expect(result.logEntries).toHaveLength(1)
            expect(result.logEntries![0].level).toBe('warn')
            expect(result.logEntries![0].message).toMatch(
                /^\[Action:action_1\] Bounce \(HardBounce\) to gone@example\.com/
            )
        })

        it.each([
            {
                name: 'events without PostHog metadata are acknowledged silently (foreign mail on the same server)',
                body: { RecordType: 'Delivery', Recipient: 'x@y.com', Metadata: { theirs: 'v' } },
                status: 200,
            },
            {
                name: 'unhandled record types are acknowledged (Open/Click stay off — the pixel records those)',
                body: { RecordType: 'Open', Metadata: {} },
                status: 200,
            },
            {
                name: 'a forged tracking code is rejected',
                body: { RecordType: 'Delivery', Metadata: { 'posthog-1': 'bm90LXJlYWw.Zm9yZ2Vk' } },
                status: 403,
            },
        ])('$name', ({ body, status }) => {
            const result = handler.handleWebhook({ body })
            expect(result.status).toBe(status)
            expect(result.metrics ?? []).toHaveLength(0)
            expect(result.optOutRecipients ?? []).toHaveLength(0)
        })

        it('test sends record no metrics or logs but still opt out on hard bounce', () => {
            const result = handler.handleWebhook({
                body: eventWith(
                    { RecordType: 'Bounce', Type: 'HardBounce', Email: 'gone@example.com' },
                    mintCode({ isTest: true })
                ),
            })
            expect(result.status).toBe(200)
            expect(result.metrics).toHaveLength(0)
            expect(result.logEntries).toHaveLength(0)
            expect(result.optOutRecipients).toEqual([{ teamId: '42', emailAddresses: ['gone@example.com'] }])
        })
    })
})
