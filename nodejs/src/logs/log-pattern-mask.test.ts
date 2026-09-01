import { createHash } from 'node:crypto'
import RE2 from 're2'

import {
    JSON_ARRAY,
    MASK_RULES,
    PATTERN_CAPS,
    PATTERN_VERSION,
    type PatternCaps,
    computeLogPattern,
    maskString,
} from './log-pattern-mask'

const caps = (overrides: Partial<PatternCaps>): PatternCaps => ({ ...PATTERN_CAPS, ...overrides })

describe('log-pattern-mask', () => {
    describe('maskString', () => {
        it.each([
            ['timestamp iso Z', 'started at 2026-08-24T10:20:45.123Z ok', 'started at <TIMESTAMP> ok'],
            ['timestamp space comma millis', 'at 2026-08-24 10:20:45,123 done', 'at <TIMESTAMP> done'],
            ['timestamp offset', 'at 2026-08-24T10:20:45+02:00 done', 'at <TIMESTAMP> done'],
            [
                'klogtime info',
                'I0827 11:39:40.307946 1 proxier.go:1484] reloading',
                'I<KLOGTIME> <N> proxier.go:<N>] reloading',
            ],
            [
                'klogtime error without micros',
                'E0827 11:39:40 1 sync.go:12] failed',
                'E<KLOGTIME> <N> sync.go:<N>] failed',
            ],
            ['klogtime warning severity', 'W0101 00:00:00 rotating', 'W<KLOGTIME> rotating'],
            ['klogtime at the MMDD upper bound', 'F1231 23:59:59 shutdown', 'F<KLOGTIME> shutdown'],
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
            ['email domain is not claimed by host', 'user@example.com sent', '<EMAIL> sent'],
            ['hex-looking labels are claimed by host, not hex', 'from deadbeefdeadbeef.com now', 'from <HOST> now'],
            ['dotted quad stays an ip, not a host', 'from 10.0.0.1 now', 'from <IP> now'],
            ['host in a url masks whole', 'GET https://api.example.io/v2/users', 'GET https://<HOST>/v2/users'],
            [
                'multi-label internal host masks whole',
                'dial capture.posthog.svc.cluster.local failed',
                'dial <HOST> failed',
            ],
            [
                'klog header is not shredded by num, so the date cannot survive as a literal',
                'I0827 11:39:40.307946 1 sync.go:12] ok',
                'I<KLOGTIME> <N> sync.go:<N>] ok',
            ],
            [
                'a count followed by a time of day is not claimed as klogtime',
                'processed 1234 12:34:56 rows',
                'processed <N> <N>:<N>:<N> rows',
            ],
        ])('ordering: %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        // The klog rule reaches text `\b\d+` cannot, so each guard is asserted from the negative
        // side too: a near-miss must fall through to `num` and keep its digits, which is what stops
        // two unrelated messages from collapsing onto one pattern.
        it.each([
            ['month 00', 'E0027 10:20:30 x', 'E0027 <N>:<N>:<N> x'],
            ['month 13', 'E1327 10:20:30 x', 'E1327 <N>:<N>:<N> x'],
            ['day 00', 'E0800 10:20:30 x', 'E0800 <N>:<N>:<N> x'],
            ['day 32', 'E0832 10:20:30 x', 'E0832 <N>:<N>:<N> x'],
            ['a year, not an MMDD', 'E2024 10:20:30 x', 'E2024 <N>:<N>:<N> x'],
            ['lowercase severity letter', 'e0827 11:39:40 x', 'e0827 <N>:<N>:<N> x'],
            ['severity letter outside IWEF', 'D0827 11:39:40 x', 'D0827 <N>:<N>:<N> x'],
            ['no word boundary before the letter', 'foobarI0827 11:39:40 x', 'foobarI0827 <N>:<N>:<N> x'],
            ['three date digits', 'I082 11:39:40 x', 'I082 <N>:<N>:<N> x'],
            ['five date digits', 'I08277 11:39:40 x', 'I08277 <N>:<N>:<N> x'],
            ['time without seconds', 'I0827 11:39 x', 'I0827 <N>:<N> x'],
            ['two spaces between date and time', 'I0827  11:39:40 x', 'I0827  <N>:<N>:<N> x'],
            ['no time at all', 'I0827 sync failed', 'I0827 sync failed'],
        ])('klogtime does not claim %s', (_name, input, expected) => {
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
            const { ruleFires } = maskString(
                'I0827 11:39:40.3 a@example.com b@example.com via api.example.net from 10.0.0.1 in 12ms'
            )
            // Summed rather than keyed by assignment: klogtime is four rules, one per severity
            // letter, so an overwriting fold would report only the last one's fires.
            const byName = MASK_RULES.reduce<Record<string, number>>(
                (acc, rule, i) => ({ ...acc, [rule.name]: (acc[rule.name] ?? 0) + ruleFires[i] }),
                {}
            )
            expect(byName).toEqual({
                timestamp: 0,
                klogtime: 1,
                uuid: 0,
                email: 2,
                host: 1,
                hex0x: 0,
                hex: 0,
                ipv4: 1,
                num: 1,
            })
        })
    })

    describe('computeLogPattern', () => {
        it('masks before truncating, so a UUID straddling the cut point still yields its placeholder', () => {
            const body = 'abcdefghij 0f2d6faf-07e3-4cff-bf47-7efa1024aee2'
            const result = computeLogPattern(body, caps({ maxOutputChars: 20 }))
            expect(result.pattern).toEqual('abcdefghij <UUID>')
            expect(result.maskedLength).toEqual('abcdefghij <UUID>'.length)
        })

        it('reports the pre-truncation masked length and truncates the pattern', () => {
            const result = computeLogPattern('x'.repeat(50), caps({ maxOutputChars: 10 }))
            expect(result.pattern).toEqual('x'.repeat(10))
            expect(result.maskedLength).toEqual(50)
        })

        it('caps the input before masking and reports it', () => {
            const result = computeLogPattern('abc 12345678', caps({ maxInputChars: 6 }))
            expect(result.inputCapped).toEqual(true)
            expect(result.pattern).toEqual('abc <N>')
        })

        it('caps the raw body before the JSON parse, so an oversized JSON body is treated as truncated prose', () => {
            const body = JSON.stringify({ message: 'x'.repeat(100) })
            const result = computeLogPattern(body, caps({ maxInputChars: 20 }))
            expect(result.inputCapped).toEqual(true)
            expect(result.bodyKind).toEqual('plaintext')
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
            ['prose body', 'plain text 3', 'plaintext', 'plain text <N>'],
        ])('body kind %s', (_name, body, expectedKind, expectedPattern) => {
            const result = computeLogPattern(body)
            expect(result.bodyKind).toEqual(expectedKind)
            expect(result.pattern).toEqual(expectedPattern)
        })

        describe('key-set identity for message-less JSON objects', () => {
            const patternOf = (body: string): string => computeLogPattern(body).pattern

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
                expect(computeLogPattern(forward).jsonKeyCount).toEqual(40)
            })

            it('reports the key count only for key-set patterns', () => {
                expect(computeLogPattern('{"a":1}').jsonKeyCount).toEqual(1)
                expect(computeLogPattern('[1,2]').jsonKeyCount).toBeUndefined()
                expect(computeLogPattern('{"message":"hi"}').jsonKeyCount).toBeUndefined()
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
        /**
         * Bodies chosen to reach every branch that decides a pattern's shape: each mask rule, the
         * message keys, the key-set and array forms, both caps, and the order of parse and cap.
         */
        const CORPUS: (string | null)[] = [
            null,
            '',
            'started at 2026-08-24T10:20:45.123Z ok',
            'I0827 11:39:40.307946 1 proxier.go:1484] reloading',
            'request 0f2d6faf-07e3-4cff-bf47-7efa1024aee2 took 7141ms',
            'mail ops@example.com via api.example.com at 10.0.0.7 slot 0xdeadbeef',
            '{"message":"user 5 logged in","level":"info"}',
            '{"msg":"served 3 requests"}',
            '{"level":"info","count":3}',
            '[1,2,3]',
            '"a bare json string with 4 words"',
            'true',
            'x'.repeat(PATTERN_CAPS.maxInputChars + 10),
            JSON.stringify({ msg: 'discovered 3 peers', pad: 'y'.repeat(PATTERN_CAPS.maxInputChars) }),
            `head ${'z'.repeat(PATTERN_CAPS.maxOutputChars)} tail`,
        ]

        /**
         * One frozen digest per version, never edited in place. Editing an entry rewrites the shape of
         * rows already in ClickHouse under that version, so the only correct fix for a red digest is a
         * new entry under a new `PATTERN_VERSION`.
         *
         * Versions before 3 predate this ratchet, so no digest was recorded for them.
         */
        const SHAPE_DIGESTS: Record<number, string> = {
            3: '1dfc6aa769551bae',
        }

        const shapeDigest = (): string =>
            createHash('sha256')
                .update(CORPUS.map((body) => computeLogPattern(body).pattern).join('\x01'))
                .digest('hex')
                .slice(0, 16)

        it('pins the emitted patterns to the current version', () => {
            // Hashing emitted patterns rather than the rules that make them is what makes this a gate:
            // MASK_RULES, PATTERN_CAPS, MESSAGE_KEYS, the key-set form, and the order of parse and cap
            // all move the digest. Do not edit the entry for the current version to make this pass.
            expect({ [PATTERN_VERSION]: shapeDigest() }).toEqual({ [PATTERN_VERSION]: SHAPE_DIGESTS[PATTERN_VERSION] })
        })

        it('carries a digest for every version since the ratchet, so a bump cannot drop its predecessor', () => {
            const recorded = Object.keys(SHAPE_DIGESTS)
                .map(Number)
                .sort((left, right) => left - right)
            const expected = Array.from({ length: PATTERN_VERSION - 2 }, (_unused, index) => index + 3)
            expect(recorded).toEqual(expected)
        })

        it('never reuses a digest across versions, so a bump without a shape change is caught', () => {
            const digests = Object.values(SHAPE_DIGESTS)
            expect(new Set(digests).size).toEqual(digests.length)
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
