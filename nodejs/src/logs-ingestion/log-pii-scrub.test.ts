import { parseJSON } from '../utils/json-parse'
import {
    PII_REDACTED,
    SENSITIVE_KEY_SUBSTRINGS,
    encodeAttributeCell,
    isSensitiveAttributeKey,
    scrubLogRecord,
    scrubPlainString,
    unwrapAttributeCell,
} from './log-pii-scrub'
import type { LogRecord } from './log-record-avro'

describe('log-pii-scrub', () => {
    describe('isSensitiveAttributeKey', () => {
        it.each(SENSITIVE_KEY_SUBSTRINGS.map((s) => [`wrap_${s}_suffix`, true] as const))(
            'detects substring %s in key',
            (key) => {
                expect(isSensitiveAttributeKey(key)).toBe(true)
            }
        )

        it.each([
            ['timestamp', false],
            ['level', false],
            ['message', false],
            ['user_id', false],
            ['meta', false],
        ])('isSensitiveAttributeKey(%s) === false', (key) => {
            expect(isSensitiveAttributeKey(key)).toBe(false)
        })

        it('is case-insensitive on the key', () => {
            expect(isSensitiveAttributeKey('USER_PASSWORD')).toBe(true)
            expect(isSensitiveAttributeKey('MyAuthorizationHeader')).toBe(true)
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

        it('stops Bearer redaction at the first non-ASCII token character (ASCII-only rule)', () => {
            expect(scrubPlainString('Bearer caf\u00E9token')).toBe(`Bearer ${PII_REDACTED}\u00E9token`)
        })

        it('does not treat fullwidth digits as card-like digits', () => {
            const panWithFullwidthOne = '4242424242\uFF1142424242'
            expect(scrubPlainString(`card ${panWithFullwidthOne} end`)).toBe(`card ${panWithFullwidthOne} end`)
        })
    })

    describe('unwrapAttributeCell / encodeAttributeCell', () => {
        it('unwraps one JSON string layer from OTLP-style cells', () => {
            expect(unwrapAttributeCell(JSON.stringify('public@example.com'))).toBe('public@example.com')
        })

        it('returns raw value when not a JSON string document', () => {
            expect(unwrapAttributeCell('plain')).toBe('plain')
        })

        it('encodes semantic strings as JSON string cells for CH', () => {
            expect(encodeAttributeCell(PII_REDACTED)).toBe(JSON.stringify(PII_REDACTED))
            expect(encodeAttributeCell('ok')).toBe('"ok"')
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
            // Use a non-sensitive key so the value is pattern-scrubbed (key `token` would full-redact the whole value).
            r.body = JSON.stringify({ user: 'a@b.co', nested: { line: 'Bearer xyz' } })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { user: string; nested: { line: string } }
            expect(parsed.user).toBe(PII_REDACTED)
            expect(parsed.nested.line).toBe(`Bearer ${PII_REDACTED}`)
        })

        it('redacts JSON body object values for sensitive keys (same rules as attribute maps)', () => {
            const r = baseRecord()
            r.body = JSON.stringify({
                password: 'hunter2',
                api_key: 'secret-value',
                note: 'no patterns',
            })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { password: string; api_key: string; note: string }
            expect(parsed.password).toBe(PII_REDACTED)
            expect(parsed.api_key).toBe(PII_REDACTED)
            expect(parsed.note).toBe('no patterns')
        })

        it('scrubs non-JSON body as plain text', () => {
            const r = baseRecord()
            r.body = 'plain err@mail.com log'
            scrubLogRecord(r)
            expect(r.body).toBe(`plain ${PII_REDACTED} log`)
        })

        it('redacts values for sensitive attribute keys as JSON cells', () => {
            const r = baseRecord()
            r.attributes = { safe: 'ok', auth_token: 'secret-value' }
            scrubLogRecord(r)
            expect(r.attributes).toEqual({
                safe: encodeAttributeCell('ok'),
                auth_token: encodeAttributeCell(PII_REDACTED),
            })
        })

        it('applies value patterns to non-sensitive attribute values as JSON cells', () => {
            const r = baseRecord()
            r.attributes = { message: 'hello user@example.com' }
            scrubLogRecord(r)
            expect(r.attributes!.message).toBe(encodeAttributeCell(`hello ${PII_REDACTED}`))
        })

        it('unwraps OTLP-style quoted cells before pattern scrub', () => {
            const r = baseRecord()
            r.attributes = { note: JSON.stringify('hello user@example.com') }
            scrubLogRecord(r)
            expect(r.attributes!.note).toBe(encodeAttributeCell(`hello ${PII_REDACTED}`))
        })

        it('scrubs resource_attributes by value when keys are not sensitive', () => {
            const r = baseRecord()
            r.resource_attributes = { host: 'srv', note: 'x@example.com' }
            scrubLogRecord(r)
            expect(r.resource_attributes!.host).toBe(encodeAttributeCell('srv'))
            expect(r.resource_attributes!.note).toBe(encodeAttributeCell(PII_REDACTED))
        })

        it('scrubs root JSON array elements (sensitive keys vs pattern scrub)', () => {
            const r = baseRecord()
            r.body = JSON.stringify([{ password: 'hunter2' }, { note: 'a@b.co' }])
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as [{ password: string }, { note: string }]
            expect(parsed[0].password).toBe(PII_REDACTED)
            expect(parsed[1].note).toBe(PII_REDACTED)
        })

        it('replaces sensitive-key JSON object values with a redacted string', () => {
            const r = baseRecord()
            r.body = JSON.stringify({ password: { nested: true }, note: 'ok' })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { password: string; note: string }
            expect(parsed.password).toBe(PII_REDACTED)
            expect(parsed.note).toBe('ok')
        })

        it.each([
            ['number', 4242424242424242],
            ['null', null],
        ] as const)('replaces sensitive-key %s leaf with redacted string', (_, leaf) => {
            const r = baseRecord()
            r.body = JSON.stringify({ api_key: leaf, ok: true })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { api_key: string; ok: boolean }
            expect(parsed.api_key).toBe(PII_REDACTED)
            expect(parsed.ok).toBe(true)
        })

        it('scrubs deeply nested sensitive keys inside JSON body', () => {
            const r = baseRecord()
            r.body = JSON.stringify({ outer: { inner: { refresh_token: 'rt-secret', label: 'x@y.co' } } })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as {
                outer: { inner: { refresh_token: string; label: string } }
            }
            expect(parsed.outer.inner.refresh_token).toBe(PII_REDACTED)
            expect(parsed.outer.inner.label).toBe(PII_REDACTED)
        })

        it('scrubs email patterns in service_name, severity_text, event_name, and instrumentation_scope', () => {
            const r = baseRecord()
            r.service_name = 'svc@corp.example'
            r.severity_text = 'warn ops@example.com'
            r.event_name = 'evt user@host.invalid'
            r.instrumentation_scope = 'scope@lib.example'
            scrubLogRecord(r)
            expect(r.service_name).toBe(PII_REDACTED)
            expect(r.severity_text).toBe(`warn ${PII_REDACTED}`)
            expect(r.event_name).toBe(`evt ${PII_REDACTED}`)
            expect(r.instrumentation_scope).toBe(PII_REDACTED)
        })
    })
})
