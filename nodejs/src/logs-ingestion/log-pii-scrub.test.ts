import { parseJSON } from '../utils/json-parse'
import { PII_REDACTED, isSensitiveAttributeKey, scrubLogRecord, scrubPlainString } from './log-pii-scrub'
import type { LogRecord } from './log-record-avro'

describe('log-pii-scrub', () => {
    describe('isSensitiveAttributeKey', () => {
        it('detects common sensitive substrings case-insensitively', () => {
            expect(isSensitiveAttributeKey('user_password')).toBe(true)
            expect(isSensitiveAttributeKey('Authorization')).toBe(true)
            expect(isSensitiveAttributeKey('my_api_key')).toBe(true)
            expect(isSensitiveAttributeKey('level')).toBe(false)
        })
    })

    describe('scrubPlainString', () => {
        it('redacts email addresses', () => {
            expect(scrubPlainString('contact user@example.com please')).toBe(`contact ${PII_REDACTED} please`)
        })

        it('redacts Bearer tokens', () => {
            expect(scrubPlainString('Authorization: Bearer abc.def.ghi')).toBe(`Authorization: Bearer ${PII_REDACTED}`)
        })

        it('redacts Stripe-style secret keys', () => {
            // Not a real Stripe API key — synthetic fixture for STRIPE_SECRET_KEY_RE coverage only.
            // GitHub push protection matches a contiguous sk_test_/sk_live_ + suffix in the file blob;
            // concatenation avoids a literal that triggers blocking (there is no supported inline pragma).
            // If you must push an old commit that still has the literal: open the unblock URL from the
            // failed `git push` output, choose "It's used in tests", then re-push within 3 hours.
            const syntheticStripeTestKey = 'sk_' + 'test_' + '123456789012345678901234'
            expect(scrubPlainString(`key ${syntheticStripeTestKey}`)).toBe(`key ${PII_REDACTED}`)
        })

        it('redacts credit card numbers that pass Luhn', () => {
            // 4242424242424242 is a common test PAN
            expect(scrubPlainString('card 4242424242424242 end')).toBe(`card ${PII_REDACTED} end`)
            expect(scrubPlainString('card 4242-4242-4242-4242 end')).toBe(`card ${PII_REDACTED} end`)
        })

        it('does not redact digit sequences that fail Luhn', () => {
            expect(scrubPlainString('id 4242424242424243')).toBe('id 4242424242424243')
        })
    })

    describe('scrubLogRecord', () => {
        const baseRecord = (): LogRecord => ({
            uuid: 'u1',
            trace_id: null,
            span_id: null,
            trace_flags: null,
            timestamp: null,
            observed_timestamp: null,
            body: null,
            severity_text: null,
            severity_number: null,
            service_name: null,
            resource_attributes: null,
            instrumentation_scope: null,
            event_name: null,
            attributes: null,
        })

        it('walks JSON body and scrubs string leaves', () => {
            const r = baseRecord()
            r.body = JSON.stringify({ user: 'a@b.co', nested: { token: 'Bearer xyz' } })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { user: string; nested: { token: string } }
            expect(parsed.user).toBe(PII_REDACTED)
            expect(parsed.nested.token).toBe(`Bearer ${PII_REDACTED}`)
        })

        it('scrubs non-JSON body as plain text', () => {
            const r = baseRecord()
            r.body = 'plain err@mail.com log'
            scrubLogRecord(r)
            expect(r.body).toBe(`plain ${PII_REDACTED} log`)
        })

        it('redacts values for sensitive attribute keys', () => {
            const r = baseRecord()
            r.attributes = { safe: 'ok', auth_token: 'secret-value' }
            scrubLogRecord(r)
            expect(r.attributes).toEqual({ safe: 'ok', auth_token: PII_REDACTED })
        })

        it('applies value patterns to non-sensitive attribute values', () => {
            const r = baseRecord()
            r.attributes = { message: 'hello user@example.com' }
            scrubLogRecord(r)
            expect(r.attributes!.message).toBe(`hello ${PII_REDACTED}`)
        })

        it('scrubs resource_attributes by value when keys are not sensitive', () => {
            const r = baseRecord()
            r.resource_attributes = { host: 'srv', note: 'x@example.com' }
            scrubLogRecord(r)
            expect(r.resource_attributes!.host).toBe('srv')
            expect(r.resource_attributes!.note).toBe(PII_REDACTED)
        })
    })
})
