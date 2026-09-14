import { resolveStandardWebhooksKey, signStandardWebhooksRequest } from './standard-webhooks'

describe('standard-webhooks', () => {
    const BASE64_SECRET = 'MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw'
    // The id, timestamp, body, and signature come from the Standard Webhooks
    // spec's reference example, so a passing test proves interoperability with
    // receivers that verify using the reference libraries.
    const WEBHOOK_ID = 'msg_p5jXN8AQM9LWM0D4loKWxJek'
    const NOW = new Date(1614265330 * 1000)
    const BODY = '{"test": 2432232314}'
    const EXPECTED_SIGNATURE = 'v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE='

    const hogFunctionWith = (value: unknown, field: 'inputs' | 'encrypted_inputs' = 'encrypted_inputs'): any => ({
        [field]: { signing_secret: { value } },
    })

    describe('resolveStandardWebhooksKey', () => {
        it.each([
            ['a whsec_ prefixed secret', `whsec_${BASE64_SECRET}`],
            ['a plain base64 secret', BASE64_SECRET],
        ])('decodes %s to the raw key bytes', (_name, secret) => {
            const resolved = resolveStandardWebhooksKey({ secret_input: 'signing_secret' }, hogFunctionWith(secret))

            expect(resolved).toEqual({ ok: true, key: Buffer.from(BASE64_SECRET, 'base64') })
        })

        it('falls back to plaintext inputs when encrypted_inputs does not carry the secret', () => {
            const resolved = resolveStandardWebhooksKey(
                { secret_input: 'signing_secret' },
                hogFunctionWith(BASE64_SECRET, 'inputs')
            )

            expect(resolved).toEqual({ ok: true, key: Buffer.from(BASE64_SECRET, 'base64') })
        })

        it.each([
            ['missing', {}],
            ['not a string', hogFunctionWith(12345)],
            ['an empty string', hogFunctionWith('')],
            ['not valid base64', hogFunctionWith('whsec_not!!valid@@base64')],
            // Lenient base64 decoding turns a truncated paste into a short or
            // even empty HMAC key, which anyone could reproduce.
            ['truncated to a single base64 character', hogFunctionWith('whsec_A')],
            ['shorter than the 24 bytes the spec requires', hogFunctionWith(`whsec_${BASE64_SECRET.slice(0, 16)}`)],
        ])('refuses to produce a key when the secret is %s', (_name, hogFunction) => {
            const resolved = resolveStandardWebhooksKey({ secret_input: 'signing_secret' }, hogFunction as any)

            expect(resolved.ok).toBe(false)
        })
    })

    describe('signStandardWebhooksRequest', () => {
        const key = Buffer.from(BASE64_SECRET, 'base64')

        it('produces the signature from the Standard Webhooks reference example', () => {
            const headers = signStandardWebhooksRequest({
                webhookId: WEBHOOK_ID,
                body: BODY,
                headers: { 'Content-Type': 'application/json' },
                key,
                now: NOW,
            })

            expect(headers).toEqual({
                'Content-Type': 'application/json',
                'webhook-id': WEBHOOK_ID,
                'webhook-timestamp': '1614265330',
                'webhook-signature': EXPECTED_SIGNATURE,
            })
        })

        it('replaces stale signing headers from a previous attempt instead of keeping them', () => {
            const headers = signStandardWebhooksRequest({
                webhookId: WEBHOOK_ID,
                body: BODY,
                headers: {
                    'Webhook-Id': 'stale-id',
                    'Webhook-Timestamp': '0',
                    'Webhook-Signature': 'v1,stale',
                    'X-Custom': 'kept',
                },
                key,
                now: NOW,
            })

            expect(headers).toEqual({
                'X-Custom': 'kept',
                'webhook-id': WEBHOOK_ID,
                'webhook-timestamp': '1614265330',
                'webhook-signature': EXPECTED_SIGNATURE,
            })
        })
    })
})
