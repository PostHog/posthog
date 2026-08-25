import { createHash } from 'node:crypto'
import RE2 from 're2'

import { JSON_ARRAY, MASK_RULES, PATTERN_VERSION, computeLogPattern, maskString } from './log-pattern-mask'

const NO_CAP = 100_000

describe('log-pattern-mask', () => {
    describe('maskString', () => {
        it.each([
            ['timestamp iso Z', 'started at 2026-08-24T10:20:45.123Z ok', 'started at <TIMESTAMP> ok'],
            ['timestamp space comma millis', 'at 2026-08-24 10:20:45,123 done', 'at <TIMESTAMP> done'],
            ['timestamp offset', 'at 2026-08-24T10:20:45+02:00 done', 'at <TIMESTAMP> done'],
            ['uuid', 'request 0f2d6faf-07e3-4cff-bf47-7efa1024aee2 failed', 'request <UUID> failed'],
            ['email', 'user alice@example.com rejected', 'user <EMAIL> rejected'],
            ['hex0x', 'fault at 0xdeadBEEF handler', 'fault at <HEX> handler'],
            ['hex long run', 'trace deadbeefdeadbeef00 end', 'trace <HEX> end'],
            ['ipv4', 'connection from 10.0.0.1 refused', 'connection from <IP> refused'],
            ['num', 'retry 5 of 7', 'retry <N> of <N>'],
        ])('rule %s masks the token and leaves neighbouring text intact', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            ['timestamp is not shredded by num', '2026-08-24T10:20:45Z', '<TIMESTAMP>'],
            ['ip octets are not eaten by num', 'peer 192.168.0.1:8080 up', 'peer <IP>:<N> up'],
            ['email starting with digits is not mangled by num', '99bottles@example.com sent', '<EMAIL> sent'],
        ])('ordering: %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            ['trailing boundary dropped', 'took 7141ms', 'took <N>ms'],
            ['leading boundary kept', 'GET /v0/export', 'GET /v0/export'],
            ['adjacent standalone numbers both mask', '5 7', '<N> <N>'],
        ])('num boundary semantics: %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it('counts fires per rule', () => {
            const { ruleFires } = maskString('a@example.com b@example.com from 10.0.0.1 in 12ms')
            const byName = Object.fromEntries(MASK_RULES.map((rule, i) => [rule.name, ruleFires[i]]))
            expect(byName).toEqual({ timestamp: 0, uuid: 0, email: 2, hex0x: 0, hex: 0, ipv4: 1, num: 1 })
        })
    })

    describe('computeLogPattern', () => {
        it('masks before truncating, so a UUID straddling the cut point still yields its placeholder', () => {
            const body = 'abcdefghij 0f2d6faf-07e3-4cff-bf47-7efa1024aee2'
            const result = computeLogPattern(body, NO_CAP, 20)
            expect(result.pattern).toEqual('abcdefghij <UUID>')
            expect(result.maskedLength).toEqual('abcdefghij <UUID>'.length)
        })

        it('reports the pre-truncation masked length and truncates the pattern', () => {
            const result = computeLogPattern('x'.repeat(50), NO_CAP, 10)
            expect(result.pattern).toEqual('x'.repeat(10))
            expect(result.maskedLength).toEqual(50)
        })

        it('caps the input before masking and reports it', () => {
            const result = computeLogPattern('abc 12345678', 6, NO_CAP)
            expect(result.inputCapped).toEqual(true)
            expect(result.pattern).toEqual('abc <N>')
        })

        it('caps the raw body before the JSON parse, so an oversized JSON body is treated as truncated prose', () => {
            const body = JSON.stringify({ message: 'x'.repeat(100) })
            const result = computeLogPattern(body, 20, NO_CAP)
            expect(result.inputCapped).toEqual(true)
            expect(result.bodyKind).toEqual('invalid_json')
            expect(result.pattern).toEqual(body.slice(0, 20))
        })

        it.each([
            ['null body', null, 'empty', ''],
            ['missing body', undefined, 'empty', ''],
            ['empty body', '', 'empty', ''],
            [
                'json object with message',
                '{"message":"user 5 in","level":"info"}',
                'json_object_or_array',
                'user <N> in',
            ],
            ['json object with msg', '{"msg":"hi 9"}', 'json_object_or_array', 'hi <N>'],
            ['json object with event', '{"event":"click 3"}', 'json_object_or_array', 'click <N>'],
            ['json object without message key', '{"level":"info"}', 'json_object_or_array', '<JSON:level>'],
            ['json array', '[1,2]', 'json_object_or_array', JSON_ARRAY],
            ['json string', '"quoted 7"', 'json_string', 'quoted <N>'],
            ['json number primitive', '42', 'primitive', '<N>'],
            ['prose body', 'plain text 3', 'invalid_json', 'plain text <N>'],
        ])('body kind %s', (_name, body, expectedKind, expectedPattern) => {
            const result = computeLogPattern(body, NO_CAP, NO_CAP)
            expect(result.bodyKind).toEqual(expectedKind)
            expect(result.pattern).toEqual(expectedPattern)
        })

        describe('key-set identity for message-less JSON objects', () => {
            const patternOf = (body: string): string => computeLogPattern(body, NO_CAP, NO_CAP).pattern

            it('is independent of source key order', () => {
                expect(patternOf('{"b":1,"a":2}')).toEqual('<JSON:a,b>')
                expect(patternOf('{"a":2,"b":1}')).toEqual('<JSON:a,b>')
            })

            it('caps at 32 keys with a dropped-key suffix, deterministically across orderings', () => {
                const keys = Array.from({ length: 40 }, (_, i) => `k${String(i).padStart(2, '0')}`)
                const forward = JSON.stringify(Object.fromEntries(keys.map((k) => [k, 1])))
                const reversed = JSON.stringify(Object.fromEntries([...keys].reverse().map((k) => [k, 1])))
                const expected = `<JSON:${keys.slice(0, 32).join(',')},+8>`
                expect(patternOf(forward)).toEqual(expected)
                expect(patternOf(reversed)).toEqual(expected)
                expect(computeLogPattern(forward, NO_CAP, NO_CAP).jsonKeyCount).toEqual(40)
            })

            it('reports the key count only for key-set patterns', () => {
                expect(computeLogPattern('{"a":1}', NO_CAP, NO_CAP).jsonKeyCount).toEqual(1)
                expect(computeLogPattern('[1,2]', NO_CAP, NO_CAP).jsonKeyCount).toBeUndefined()
                expect(computeLogPattern('{"message":"hi"}', NO_CAP, NO_CAP).jsonKeyCount).toBeUndefined()
            })

            it('renders an empty object as an empty key set', () => {
                expect(patternOf('{}')).toEqual('<JSON:>')
            })

            it('takes only top-level keys from nested objects', () => {
                expect(patternOf('{"outer":{"inner":1},"other":[1,2]}')).toEqual('<JSON:other,outer>')
            })

            it('never masks keys, so value-shaped keys stay verbatim', () => {
                expect(patternOf('{"10.0.0.1":1,"7141":2,"user@example.com":3}')).toEqual(
                    '<JSON:10.0.0.1,7141,user@example.com>'
                )
            })
        })
    })

    describe('PATTERN_VERSION ratchet', () => {
        it('moves whenever MASK_RULES changes', () => {
            const digest = createHash('sha256')
                .update(MASK_RULES.map((rule) => `${rule.name}\0${rule.pattern}\0${rule.replacement}`).join('\x01'))
                .digest('hex')
                .slice(0, 16)
            expect({ version: PATTERN_VERSION, digest }).toEqual({ version: 1, digest: 'd8b059c25a24983d' })
        })
    })

    describe('RE2 ratchet', () => {
        it.each(MASK_RULES.map((rule) => [rule.name, rule.pattern] as const))(
            'rule %s compiles under RE2 and uses no lookaround, backreference, or capture group',
            (_name, pattern) => {
                expect(() => new RE2(pattern, 'g')).not.toThrow()
                expect(pattern).not.toMatch(/\(\?=|\(\?!|\(\?</)
                expect(pattern).not.toMatch(/\\[1-9]/)
                expect(pattern.replace(/\\\(/g, '')).not.toMatch(/\((?!\?)/)
            }
        )
    })

    describe('node/ClickHouse agreement', () => {
        const sequentialChain = (input: string): string =>
            MASK_RULES.reduce((acc, rule) => acc.replace(new RE2(rule.pattern, 'g'), rule.replacement), input)

        const corpus = [
            'events rate limited by distinct_id -- person processing disabled',
            'geoIP computation error: The address 203.0.113.7 is not in the database.',
            '2026-08-24T10:20:45.123Z error in worker 12: connect ECONNREFUSED 10.0.0.1:6379',
            'request 0f2d6faf-07e3-4cff-bf47-7efa1024aee2 for alice@example.com took 7141ms',
            'checksum deadbeefdeadbeef00 at offset 0x7fff5fbff8c0',
            'GET /v0/export?since=1724495000 -> 200 in 35ms',
            'lag=1.5s status=500 retries=3',
            'batch 5 7 11 done at 2026-08-24 10:20:45,001',
            'no variable parts in this line at all',
            'mixed a99@example.com then 192.168.0.1 then 99bottles@example.com',
        ]

        it.each(corpus.map((line) => [line] as const))('%s', (line) => {
            expect(maskString(line).masked).toEqual(sequentialChain(line))
        })
    })
})
