import { createHash } from 'node:crypto'
import RE2 from 're2'

import {
    JSON_ARRAY,
    KEY_SET_MAX_KEYS,
    type LogPatternResult,
    MASK_RULES,
    PATTERN_CAPS,
    PATTERN_VERSION,
    buildLogPattern,
    maskString,
} from './log-pattern-mask'

describe('log-pattern-mask', () => {
    // The list is per team in production, so no single list is a global shape input. The ratchet
    // below pins this one so the digest keeps covering the masker and the selection mechanism, and
    // makes no claim about any team's configured list.
    const TEST_MESSAGE_KEYS: readonly string[] = ['message', 'msg', 'event']
    const patternResult = (body: string | null | undefined): LogPatternResult =>
        buildLogPattern(body, TEST_MESSAGE_KEYS)

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

    describe('buildLogPattern', () => {
        it('masks before truncating, so a UUID straddling the cut point still yields its placeholder', () => {
            // Long enough that the raw UUID crosses the output cap, short enough that `<UUID>` does not.
            // Filled with a non-hex letter, or the run itself masks to `<HEX>`.
            const head = 'z'.repeat(PATTERN_CAPS.maxOutputChars - 24)
            const body = `${head} 0f2d6faf-07e3-4cff-bf47-7efa1024aee2`
            expect(body.length).toBeGreaterThan(PATTERN_CAPS.maxOutputChars)

            const result = patternResult(body)
            expect(result.pattern).toEqual(`${head} <UUID>`)
            expect(result.maskedLength).toEqual(`${head} <UUID>`.length)
        })

        it('reports the pre-truncation masked length and truncates the pattern', () => {
            const result = patternResult('x'.repeat(PATTERN_CAPS.maxOutputChars * 2))
            expect(result.pattern).toEqual('x'.repeat(PATTERN_CAPS.maxOutputChars))
            expect(result.maskedLength).toEqual(PATTERN_CAPS.maxOutputChars * 2)
        })

        it('caps the input before masking and reports it', () => {
            const result = patternResult(`${'z'.repeat(PATTERN_CAPS.maxInputChars)} 12345678`)
            expect(result.inputCapped).toEqual(true)
            // The number sat past the input cap, so no rule ever saw it.
            expect(result.maskedLength).toEqual(PATTERN_CAPS.maxInputChars)
            expect(result.ruleFires.every((fires) => fires === 0)).toEqual(true)
        })

        it('caps the raw body before the JSON parse, so an oversized JSON body is treated as truncated prose', () => {
            const body = JSON.stringify({ message: 'x'.repeat(PATTERN_CAPS.maxInputChars) })
            const result = patternResult(body)
            expect(result.inputCapped).toEqual(true)
            expect(result.bodyKind).toEqual('plaintext')
            expect(result.pattern).toEqual(body.slice(0, PATTERN_CAPS.maxOutputChars))
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
            ['json object behind leading whitespace', ' \n\t{"msg":"hi 9"}', 'json_object_or_array', 'hi <N>'],
            ['prose body that opens like JSON', 'null pointer at line 4', 'plaintext', 'null pointer at line <N>'],
        ])('body kind %s', (_name, body, expectedKind, expectedPattern) => {
            const result = patternResult(body)
            expect(result.bodyKind).toEqual(expectedKind)
            expect(result.pattern).toEqual(expectedPattern)
        })

        describe('key-set identity for message-less JSON objects', () => {
            const patternOf = (body: string): string => patternResult(body).pattern

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
                expect(patternResult(forward).jsonKeyCount).toEqual(40)
            })

            it('reports the key count only for key-set patterns', () => {
                expect(patternResult('{"a":1}').jsonKeyCount).toEqual(1)
                expect(patternResult('[1,2]').jsonKeyCount).toBeUndefined()
                expect(patternResult('{"message":"hi"}').jsonKeyCount).toBeUndefined()
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
         *
         * The message-key bodies are derived from `TEST_MESSAGE_KEYS`, the fixed list the ratchet is
         * pinned to. Mask rules cannot be derived that way, so a coverage test below holds the
         * equivalent line for them.
         */
        const CORPUS: (string | null)[] = [
            null,
            '',
            'started at 2026-08-24T10:20:45.123Z ok',
            'I0827 11:39:40.307946 1 proxier.go:1484] reloading',
            'W0101 00:00:00 rotate E0102 01:02:03 retry F0103 02:03:04 exit',
            'request 0f2d6faf-07e3-4cff-bf47-7efa1024aee2 took 7141ms',
            'mail ops@example.com via api.example.com at 10.0.0.7 slot 0xdeadbeef',
            'checksum deadbeefdeadbeef00 verified',
            ...TEST_MESSAGE_KEYS.map((key) => JSON.stringify({ [key]: 'served 3 requests', level: 'info' })),
            '{"msg":"loses 2","message":"wins 1"}',
            // Reach `extractJsonMessage` itself, not just the keys it reads. Widening it to accept a
            // number, or trimming what it returns, reshapes real bodies while leaving every other
            // corpus pattern byte-identical.
            '{"msg":12345}',
            '{"msg":"  padded 3  "}',
            '{"level":"info","count":3}',
            '{}',
            JSON.stringify(Object.fromEntries(Array.from({ length: 40 }, (_unused, index) => [`k${index}`, 1]))),
            '[1,2,3]',
            '"a bare json string with 4 words"',
            'true',
            'x'.repeat(PATTERN_CAPS.maxInputChars + 10),
            JSON.stringify({ msg: 'discovered 3 peers', pad: 'y'.repeat(PATTERN_CAPS.maxInputChars) }),
            `head ${'z'.repeat(PATTERN_CAPS.maxOutputChars)} tail`,
        ]

        const RATCHET_FIRST_VERSION = 3

        /**
         * One frozen digest per version. A red digest means the emitted shape moved, and the only correct
         * fix is a new entry under a new `PATTERN_VERSION` — editing an entry in place relabels rows
         * already in ClickHouse under that version. The one exception is growing `CORPUS`, which moves the
         * digest without moving the shape. Growing `SHAPE_INPUTS` does the same. Re-record for either only
         * in a commit that moves no emitted pattern, and say so in the message.
         *
         * Versions before `RATCHET_FIRST_VERSION` predate this ratchet, so no digest was recorded for them.
         */
        const SHAPE_DIGESTS: Record<number, string> = {
            3: 'd7b045b1054244d1',
        }

        /**
         * The shape inputs no corpus body can reveal, hashed alongside the patterns the corpus emits.
         *
         * Emitted patterns catch control flow — the order of parse and cap, the key-set form — which a
         * hash of the rules cannot see. They do not catch a rule broadened without changing what the
         * corpus emits: adding a TLD to `host`, or widening `hex` from 16 chars to 12, leaves every
         * corpus pattern byte-identical while real bodies change shape. Neither half covers the other,
         * so the digest takes both.
         */
        const SHAPE_INPUTS = JSON.stringify({
            rules: MASK_RULES.map((rule) => [rule.name, rule.pattern, rule.replacement]),
            caps: PATTERN_CAPS,
            messageKeys: TEST_MESSAGE_KEYS,
            keySetMaxKeys: KEY_SET_MAX_KEYS,
            jsonArray: JSON_ARRAY,
        })

        const shapeDigest = (): string =>
            createHash('sha256')
                .update([SHAPE_INPUTS, ...CORPUS.map((body) => patternResult(body).pattern)].join('\x01'))
                .digest('hex')
                .slice(0, 16)

        it('pins the emitted patterns to the current version', () => {
            expect({ [PATTERN_VERSION]: shapeDigest() }).toEqual({ [PATTERN_VERSION]: SHAPE_DIGESTS[PATTERN_VERSION] })
        })

        it('reaches every mask rule, so a new rule cannot land without moving the digest', () => {
            const fires = MASK_RULES.map(() => 0)
            for (const body of CORPUS) {
                patternResult(body).ruleFires.forEach((count, index) => (fires[index] += count))
            }
            // Reported by pattern, not name: klogtime is four rules under one name, so a name would
            // not say which of them the corpus misses.
            expect(MASK_RULES.filter((_rule, index) => fires[index] === 0).map((rule) => rule.pattern)).toEqual([])
        })

        it('reaches every body kind, so a parse change cannot land without moving the digest', () => {
            // `parseLogBodyForIngestion` picks which branch of `computeLogPattern` runs, and it lives in
            // another module that neither half of the digest hashes. Reaching every kind is what makes a
            // change over there surface as a moved digest instead of as silence.
            const kinds = [...new Set(CORPUS.map((body) => patternResult(body).bodyKind))].sort()
            expect(kinds).toEqual(['empty', 'json_object_or_array', 'json_string', 'plaintext', 'primitive'])
        })

        it('carries a digest for every version since the ratchet, so a bump cannot drop its predecessor', () => {
            const recorded = Object.keys(SHAPE_DIGESTS)
                .map(Number)
                .sort((left, right) => left - right)
            const expected = Array.from(
                { length: PATTERN_VERSION - RATCHET_FIRST_VERSION + 1 },
                (_unused, index) => RATCHET_FIRST_VERSION + index
            )
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
