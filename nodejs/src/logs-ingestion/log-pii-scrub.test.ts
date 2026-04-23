import { parseJSON } from '../utils/json-parse'
import { PII_REDACTED, encodeAttributeCell, scrubLogRecord, scrubPlainString } from './log-pii-scrub'
import type { LogRecord } from './log-record-avro'

describe('log-pii-scrub', () => {
    describe('encodeAttributeCell', () => {
        it('encodes semantic strings as JSON string cells for CH', () => {
            expect(encodeAttributeCell(PII_REDACTED)).toBe(JSON.stringify(PII_REDACTED))
            expect(encodeAttributeCell('ok')).toBe('"ok"')
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
            const syntheticStripeTestKey = 'sk_' + 'test_' + '123456789012345678901234'
            expect(scrubPlainString(`key ${syntheticStripeTestKey}`)).toBe(`key ${PII_REDACTED}`)
        })

        it('does not redact PAN-like digit runs (lite scrub)', () => {
            expect(scrubPlainString('card 4242424242424242 end')).toBe('card 4242424242424242 end')
            expect(scrubPlainString('card 4242-4242-4242-4242 end')).toBe('card 4242-4242-4242-4242 end')
            expect(scrubPlainString('id 4242424242424243')).toBe('id 4242424242424243')
        })

        it('stops Bearer redaction at the first non-ASCII token character (ASCII-only rule)', () => {
            expect(scrubPlainString('Bearer caf\u00E9token')).toBe(`Bearer ${PII_REDACTED}\u00E9token`)
        })

        it('leaves digit runs with fullwidth digits unchanged', () => {
            const panWithFullwidthOne = '4242424242\uFF1142424242'
            expect(scrubPlainString(`card ${panWithFullwidthOne} end`)).toBe(`card ${panWithFullwidthOne} end`)
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

        it('scrubs pattern-shaped PII inside a JSON body string without parsing the JSON tree', () => {
            const r = baseRecord()
            r.body = JSON.stringify({ user: 'a@b.co', nested: { line: 'Bearer xyz' } })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { user: string; nested: { line: string } }
            expect(parsed.user).toBe(PII_REDACTED)
            expect(parsed.nested.line).toBe(`Bearer ${PII_REDACTED}`)
        })

        it('does not redact JSON body values by object key alone (opaque secrets stay unless pattern matches)', () => {
            const r = baseRecord()
            r.body = JSON.stringify({
                password: 'hunter2',
                api_key: 'secret-value',
                note: 'no patterns',
            })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { password: string; api_key: string; note: string }
            expect(parsed.password).toBe('hunter2')
            expect(parsed.api_key).toBe('secret-value')
            expect(parsed.note).toBe('no patterns')
        })

        it('scrubs non-JSON body as plain text', () => {
            const r = baseRecord()
            r.body = 'plain err@mail.com log'
            scrubLogRecord(r)
            expect(r.body).toBe(`plain ${PII_REDACTED} log`)
        })

        it('does not mutate attributes, resource_attributes, or metadata string fields', () => {
            const r = baseRecord()
            r.body = 'ok'
            r.attributes = { safe: 'ok', auth_token: 'secret@x.com' }
            r.resource_attributes = { host: 'srv', note: 'x@example.com' }
            r.service_name = 'svc@corp.example'
            r.severity_text = 'warn ops@example.com'
            r.event_name = 'evt user@host.invalid'
            r.instrumentation_scope = 'scope@lib.example'
            scrubLogRecord(r)
            expect(r.body).toBe('ok')
            expect(r.attributes).toEqual({ safe: 'ok', auth_token: 'secret@x.com' })
            expect(r.resource_attributes).toEqual({ host: 'srv', note: 'x@example.com' })
            expect(r.service_name).toBe('svc@corp.example')
            expect(r.severity_text).toBe('warn ops@example.com')
            expect(r.event_name).toBe('evt user@host.invalid')
            expect(r.instrumentation_scope).toBe('scope@lib.example')
        })

        it('scrubs pattern-shaped PII in JSON array body string; does not redact by JSON key alone', () => {
            const r = baseRecord()
            r.body = JSON.stringify([{ password: 'hunter2' }, { note: 'a@b.co' }])
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as [{ password: string }, { note: string }]
            expect(parsed[0].password).toBe('hunter2')
            expect(parsed[1].note).toBe(PII_REDACTED)
        })

        it('leaves sensitive-key object values in JSON body unchanged when no pattern matches', () => {
            const r = baseRecord()
            r.body = JSON.stringify({ password: { nested: true }, note: 'ok' })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { password: { nested: boolean }; note: string }
            expect(parsed.password).toEqual({ nested: true })
            expect(parsed.note).toBe('ok')
        })

        it.each([
            ['number', 12345],
            ['null', null],
        ] as const)('leaves sensitive-key %s leaf in JSON body unchanged when no pattern matches', (_, leaf) => {
            const r = baseRecord()
            r.body = JSON.stringify({ api_key: leaf, ok: true })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as { api_key: number | null; ok: boolean }
            expect(parsed.api_key).toBe(leaf)
            expect(parsed.ok).toBe(true)
        })

        it('scrubs email in nested JSON body string; opaque token values stay unless patterned', () => {
            const r = baseRecord()
            r.body = JSON.stringify({ outer: { inner: { refresh_token: 'rt-secret', label: 'x@y.co' } } })
            scrubLogRecord(r)
            const parsed = parseJSON(r.body!) as {
                outer: { inner: { refresh_token: string; label: string } }
            }
            expect(parsed.outer.inner.refresh_token).toBe('rt-secret')
            expect(parsed.outer.inner.label).toBe(PII_REDACTED)
        })

        it('does not mutate trace_id or span_id buffers', () => {
            const r = baseRecord()
            r.trace_id = Buffer.from([1, 2, 3, 4, 5, 6, 7, 8])
            r.span_id = Buffer.from([9, 9, 9])
            r.trace_flags = 1
            r.timestamp = 1_700_000_000_000_000
            r.observed_timestamp = 1_700_000_000_000_001
            r.body = 'user@example.com'
            scrubLogRecord(r)
            expect(r.trace_id).toEqual(Buffer.from([1, 2, 3, 4, 5, 6, 7, 8]))
            expect(r.span_id).toEqual(Buffer.from([9, 9, 9]))
            expect(r.trace_flags).toBe(1)
            expect(r.timestamp).toBe(1_700_000_000_000_000)
            expect(r.observed_timestamp).toBe(1_700_000_000_000_001)
            expect(r.body).toBe(PII_REDACTED)
        })
    })
})
