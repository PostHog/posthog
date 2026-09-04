import RE2 from 're2'

import { parseJSON } from '~/common/utils/json-parse'

import {
    PII_REDACTED,
    PII_RULES,
    encodeAttributeCell,
    scrubLogRecord,
    scrubPlainString,
    scrubPlainStringWithStats,
} from './log-pii-scrub'
import type { LogRecord } from './log-record-avro'

describe('log-pii-scrub', () => {
    describe('encodeAttributeCell', () => {
        it('encodes semantic strings as JSON string cells for CH', () => {
            expect(encodeAttributeCell(PII_REDACTED)).toBe(JSON.stringify(PII_REDACTED))
            expect(encodeAttributeCell('ok')).toBe('"ok"')
        })
    })

    describe('scrubPlainString', () => {
        // Bearer keeps its prefix, so it is the one shape the table below cannot assert.
        it('redacts Bearer tokens', () => {
            expect(scrubPlainString('Authorization: Bearer abc.def.ghi')).toBe(`Authorization: Bearer ${PII_REDACTED}`)
        })

        // Secrets are built by concatenation, so no line of this file reads as a live credential to
        // a secret scanner.
        it.each([
            ['email addresses', 'user@example.com'],
            ['Stripe-style secret keys', 'sk_' + 'test_' + '123456789012345678901234'],
            ['GitHub personal access tokens', 'gh' + 'p_' + 'A1b2C3d4E5f6G7h8I9j0KlMnOpQrStUvWxYz'],
            ['GitHub server tokens', 'gh' + 's_' + 'A1b2C3d4E5f6G7h8I9j0KlMnOpQrStUvWxYz'],
            ['Slack tokens', 'xox' + 'b-' + '123456789012-abcdefghijkl'],
            ['AWS access key ids', 'AKIA' + 'IOSFODNN7EXAMPLE'],
            ['JWTs', 'ey' + 'JhbGciOiJIUzI1NiJ9' + '.' + 'eyJzdWIiOiIxMjMifQ' + '.' + 'S1gnAtUr3-_x'],
        ])('redacts %s', (_label, secret) => {
            expect(scrubPlainString(`credential ${secret} rejected`)).toBe(`credential ${PII_REDACTED} rejected`)
        })

        it.each([
            ['a word that opens like a GitHub prefix', 'ghost_writer opened a file'],
            ['a truncated AWS key id', 'AKIAIOSFODNN7 is too short'],
            ['a base64 word that is not a JWT', 'eyJhbGciOiJIUzI1NiJ9 alone'],
        ])('leaves %s alone', (_label, input) => {
            expect(scrubPlainString(input)).toBe(input)
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

    describe('scrubPlainStringWithStats', () => {
        // Matches `sk_(?:live|test)_[a-zA-Z0-9]{20,}` — keep construction split like scrubPlainString tests.
        const syntheticStripeTestKey = 'sk_' + 'test_' + '123456789012345678901234'

        it.each([
            {
                _label: 'no pattern matches',
                input: 'no patterns here',
                expected: { output: 'no patterns here', piiReplacements: 0 },
            },
            {
                _label: 'one count per email address',
                input: 'a@b.com and c@d.com',
                expected: { output: `${PII_REDACTED} and ${PII_REDACTED}`, piiReplacements: 2 },
            },
            {
                _label: 'Bearer-shaped token: one count, preserves Bearer prefix in output',
                input: 'Authorization: Bearer abc.def.ghi',
                expected: { output: `Authorization: Bearer ${PII_REDACTED}`, piiReplacements: 1 },
            },
            {
                _label: 'Stripe sk_ key: one count',
                input: `key ${syntheticStripeTestKey} end`,
                expected: { output: `key ${PII_REDACTED} end`, piiReplacements: 1 },
            },
            {
                _label: 'Bearer, Stripe, and email each add one to the count',
                input: `Authorization: Bearer abc.def.ghi ${syntheticStripeTestKey} a@b.co`,
                expected: {
                    output: `Authorization: Bearer ${PII_REDACTED} ${PII_REDACTED} ${PII_REDACTED}`,
                    piiReplacements: 3,
                },
            },
        ] as const)('$_label', ({ input, expected }) => {
            expect(scrubPlainStringWithStats(input)).toEqual(expected)
        })

        it('scrubs a multi-megabyte value with thousands of matches without a quadratic stall', () => {
            const EMAIL_COUNT = 8000
            const MAX_DURATION_MS = 1000
            const filler = 'x'.repeat(240)
            const input = Array.from({ length: EMAIL_COUNT }, (_, i) => `user${i}@example.com ${filler}`).join(' ')

            const startedAt = performance.now()
            const { output, piiReplacements } = scrubPlainStringWithStats(input)
            const durationMs = performance.now() - startedAt

            expect(piiReplacements).toBe(EMAIL_COUNT)
            expect(output).not.toContain('@example.com')
            expect(output.split(PII_REDACTED)).toHaveLength(EMAIL_COUNT + 1)
            expect(durationMs).toBeLessThan(MAX_DURATION_MS)
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

        it('scrubs pattern-shaped PII in log attributes; does not mutate resource_attributes or metadata string fields', () => {
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
            expect(r.attributes).toEqual({ safe: 'ok', auth_token: PII_REDACTED })
            expect(r.resource_attributes).toEqual({ host: 'srv', note: 'x@example.com' })
            expect(r.service_name).toBe('svc@corp.example')
            expect(r.severity_text).toBe('warn ops@example.com')
            expect(r.event_name).toBe('evt user@host.invalid')
            expect(r.instrumentation_scope).toBe('scope@lib.example')
        })

        it('scrubs log attributes when body is null (no early return)', () => {
            const r = baseRecord()
            r.body = null
            r.attributes = { x: 'a@b.co' }
            const stats = scrubLogRecord(r)
            expect(r.attributes).toEqual({ x: PII_REDACTED })
            expect(stats.piiReplacements).toBe(1)
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

    // The redaction loop reads the fired rule off the capture-group index, so a rule that adds a
    // group of its own shifts every rule after it and applies the wrong replacement. That failure is
    // silent: an email would redact as `Bearer {{REDACTED}}`, or a real credential would not redact
    // at all. `MASK_RULES` carries the same ratchet.
    describe('RE2 ratchet', () => {
        it.each(PII_RULES.map((rule) => [rule.name, rule.pattern] as const))(
            'rule %s compiles under RE2 and uses no lookaround, backreference, or capture group',
            (_name, pattern) => {
                expect(() => new RE2(pattern, 'g')).not.toThrow()
                expect(pattern).not.toMatch(/\(\?=|\(\?!|\(\?</)
                expect(pattern).not.toMatch(/\\[1-9]/)
                expect(pattern.replace(/\\\(/g, '')).not.toMatch(/\((?!\?)/)
            }
        )
    })
})
