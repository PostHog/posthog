import { createHash } from 'node:crypto'
import RE2 from 're2'

import {
    JSON_ARRAY,
    KEY_SET_MAX_KEYS,
    type LogPatternResult,
    MASK_RULES,
    MESSAGE_KEYS,
    PATTERN_CAPS,
    PATTERN_VERSION,
    buildLogPattern,
    maskString,
} from './log-pattern-mask'

describe('log-pattern-mask', () => {
    const patternResult = (body: string | null | undefined): LogPatternResult => buildLogPattern(body, MESSAGE_KEYS)

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
            ['clftime', '10.0.0.1 - - [02/Jan/2026:03:04:05 +0000] "GET /a"', '<IP> - - [<TIMESTAMP>] "GET /a"'],
            ['ctime with a zone', 'booted Mon Jan  2 03:04:05 UTC 2026 ok', 'booted <TIMESTAMP> ok'],
            ['ctime without a zone', 'booted Mon Jan 12 03:04:05 2026 ok', 'booted <TIMESTAMP> ok'],
            ['httpdate', 'expires Mon, 02 Jan 2026 03:04:05 GMT now', 'expires <TIMESTAMP> now'],
            ['syslogtime', 'Jan  2 03:04:05 host sshd: accepted', '<TIMESTAMP> host sshd: accepted'],
            ['id', 'charging cus_Qz4WmTb7Kx9pLr now', 'charging <ID> now'],
            ['stripeid', 'charging cus_QzWmTbKxRpLvNa now', 'charging <ID> now'],
            ['snakenum', 'folder team_190219 ready', 'folder team_<N> ready'],
            ['uuid', 'request 0f2d6faf-07e3-4cff-bf47-7efa1024aee2 failed', 'request <UUID> failed'],
            ['email', 'user alice@example.com rejected', 'user <EMAIL> rejected'],
            ['hex0x', 'fault at 0xdeadBEEF handler', 'fault at <HEX> handler'],
            ['hex long run', 'trace deadbeefdeadbeef00 end', 'trace <HEX> end'],
            ['hex at the short floor', 'built sha a3f9c1d2 ok', 'built sha <HEX> ok'],
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
            ['email with an id-shaped local part is not split by id', 'john_D2oe@example.com sent', '<EMAIL> sent'],
            ['hex-looking labels are claimed by host, not hex', 'from deadbeefdeadbeef.com now', 'from <HOST> now'],
            [
                'a lowercase uuid behind a prefix stays a uuid, because the id rule needs an uppercase letter',
                'job_0f2d6faf-07e3-4cff-bf47-7efa1024aee2 queued',
                'job_<UUID> queued',
            ],
            [
                'a uuid at the end of a digit chain stays a uuid, so its tail cannot leak',
                'export job_1234_01905063-07e3-4cff-bf47-7efa1024aee2 done',
                'export job_<N>_<UUID> done',
            ],
            [
                'an uppercase uuid at the end of a digit chain stays a uuid',
                'export job_1234_01905063-07E3-4CFF-BF47-7EFA1024AEE2 done',
                'export job_<N>_<UUID> done',
            ],
            [
                'digits glued to a uuid at the end of a digit chain mask with it',
                'copy x_1234_123456789012-07e3-4cff-bf47-7efa1024aee2 done',
                'copy x_<N>_<UUID> done',
            ],
            [
                'a hex run glued to a uuid at the end of a digit chain masks with it',
                'copy x_1234_ab12cd34ef-07e3-4cff-bf47-7efa1024aee2 done',
                'copy x_<N>_<UUID> done',
            ],
            [
                'a short digit run before a uuid stays literal',
                'copy v_12_01905063-07e3-4cff-bf47-7efa1024aee2 done',
                'copy v_12_<UUID> done',
            ],
            [
                'digits glued to the front of a uuid mask with it, not as a stranded number',
                'copy x_123456789012-07e3-4cff-bf47-7efa1024aee2 done',
                'copy x_<UUID> done',
            ],
            [
                'a hex run glued to the front of a uuid masks with it',
                'copy x_1234abcdef01-07e3-4cff-bf47-7efa1024aee2 done',
                'copy x_<UUID> done',
            ],
            [
                'a uuid behind an underscore whose first group is all digits stays a uuid, not a number',
                'job_12345678-07e3-4cff-bf47-7efa1024aee2 queued',
                'job_<UUID> queued',
            ],
            ['an email whose local part ends in digits stays an email', 'ops_12345@example.com sent', '<EMAIL> sent'],
            ['digits after an underscore inside an id stay with the id', 'key_1234Ab9 rotated', '<ID> rotated'],
            [
                'an underscore-joined host label keeps its host mask',
                'dial shard_1234.example.com now',
                'dial shard_<N>.<HOST> now',
            ],
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
            [
                'a ctime line loses its weekday, which the month rule alone would strand',
                'Mon Jan  2 03:04:05 UTC 2026 boot',
                '<TIMESTAMP> boot',
            ],
            ['an http date loses its weekday too', 'Mon, 02 Jan 2026 03:04:05 GMT boot', '<TIMESTAMP> boot'],
        ])('ordering: %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        // Each name-carrying date rule needs a real date around the name, for the same reason the
        // klog guards are asserted from the negative side: a bare month or weekday is ordinary
        // English, and masking it would merge lines that have nothing to do with each other.
        it.each([
            ['a bare month name in prose', 'May retry 3 times', 'May retry <N> times'],
            ['a bare weekday in prose', 'Mon deploy window 2', 'Mon deploy window <N>'],
            ['a month name without a time', 'Jan 2 rows written', 'Jan <N> rows written'],
            ['a weekday with a time but no date', 'Mon 03:04:05 tick', 'Mon <N>:<N>:<N> tick'],
            ['a day of month above 31', 'Jan 32 03:04:05 x', 'Jan <N> <N>:<N>:<N> x'],
            // A severity word has the shape of a zone, and a count has the shape of a year, so an
            // open zone or year lets `ctime` take both out of the pattern and merge an ERROR line
            // with a WARN one. The count here sits inside the year range the rule accepts, which is
            // where an open zone alone still loses it.
            [
                'a severity word and the count behind it',
                'Mon Jan  2 03:04:05 ERROR 2341 connections',
                '<TIMESTAMP> ERROR <N> connections',
            ],
            [
                'a count that reads exactly like this year',
                'Mon Jan  2 03:04:05 WARN 2026 connections',
                '<TIMESTAMP> WARN <N> connections',
            ],
            // An unlisted zone costs grouping, not correctness: the date still masks, and the zone
            // and year stay rather than disappearing with it.
            [
                'a zone outside the known set, which falls to the month rule',
                'booted Mon Jan  2 03:04:05 XYZQ 2026 ok',
                'booted <TIMESTAMP> XYZQ <N> ok',
            ],
            [
                'an impossible day in an http date',
                'Mon, 99 Jan 2026 03:04:05 GMT open',
                'Mon, <N> Jan <N> <N>:<N>:<N> GMT open',
            ],
        ])('date rules do not claim %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            ['shared object files are not hosts', 'loading libssl.so failed', 'loading libssl.so failed'],
            ['shell scripts are not hosts', 'running deploy.sh in 2s', 'running deploy.sh in <N>s'],
        ])('%s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            ['a ulid-shaped id', 'claimed org_01ABCDEF23GHJK45MNPQRS67 lease', 'claimed <ID> lease'],
            [
                'an id inside a url path',
                'GET /v1/customers/cus_Vn8QjTz3Rw6Kp2/payment_methods',
                'GET /v1/customers/<ID>/payment_methods',
            ],
            ['a hyphenated id whole', 'span sess_3Ih3uQk-9Xz2 closed', 'span <ID> closed'],
            [
                'an uppercase uuid behind a prefix whole, tail included',
                'trace_0A1B2C3D-4E5F-6789-ABCD-EF0123456789 started',
                '<ID> started',
            ],
        ])('id masks %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            ['a snake_case word', 'listing push_subscriptions for team', 'listing push_subscriptions for team'],
            [
                'a snake_case url path segment',
                'GET /v1/entitlements/active_entitlements?limit=100',
                'GET /v1/entitlements/active_entitlements?limit=<N>',
            ],
            ['a body of digits only', 'folder team_123456 ready', 'folder team_<N> ready'],
            ['a body of lowercase and digits', 'repo repo_0a1b2c3d synced', 'repo repo_0a1b2c3d synced'],
            ['a body of letters but no digit', 'saw ref_QzWmTbKx once', 'saw ref_QzWmTbKx once'],
            ['a prefix past the cap', 'saw verylongprefix_Zq8xTv2wPn once', 'saw verylongprefix_Zq8xTv2wPn once'],
        ])('id does not claim %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            ['a 24-letter subscription id', 'renewed sub_QzWmTbKxRpLvNaQzWmTbKxRp ok', 'renewed <ID> ok'],
            ['an all-uppercase id', 'charging cus_UGCOPIHBEGXJIF now', 'charging <ID> now'],
            [
                'an id inside a url path',
                'GET /v1/customers/cus_TjuwpGlQcCSDCk/payment_methods',
                'GET /v1/customers/<ID>/payment_methods',
            ],
            [
                'a PascalCase name of exactly 14 letters, a known limit',
                'calling sub_PaymentMethods now',
                'calling <ID> now',
            ],
        ])('stripeid masks %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            ['a snake_case word', 'reading sub_categorization now', 'reading sub_categorization now'],
            [
                'a prefix glued to a longer word',
                'saw stripe_cus_QzWmTbKxRpLvNa once',
                'saw stripe_cus_QzWmTbKxRpLvNa once',
            ],
            ['another Stripe prefix, payment intent', 'saw pi_QzWmTbKxRpLvNa once', 'saw pi_QzWmTbKxRpLvNa once'],
            ['another Stripe prefix, charge', 'saw ch_QzWmTbKxRpLvNa once', 'saw ch_QzWmTbKxRpLvNa once'],
        ])('stripeid does not claim %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            [
                'a ClickHouse part name whole, merge level included',
                'No active replica has part 202610_4682747_4682751_2 or covering part',
                'No active replica has part <N>_<N> or covering part',
            ],
            ['a dated backup suffix', 'restored db_20260425_112424 from backup', 'restored db_<N> from backup'],
            ['a long query id', 'running hubspot_sync__query_1792084441 now', 'running hubspot_sync__query_<N> now'],
            ['a year after an underscore, as num masks a bare year', 'report daily_2026 sent', 'report daily_<N> sent'],
            ['a nanosecond epoch', 'flushed batch_1792084441123456789 ok', 'flushed batch_<N> ok'],
            [
                'a 4-digit vendor error code, as num masks its hyphen form',
                'failed with ERR_ACME_3200',
                'failed with ERR_ACME_<N>',
            ],
        ])('snakenum masks %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        it.each([
            ['an architecture', 'built for x86_64 linux', 'built for x86_64 linux'],
            ['a key size', 'cipher aes_256 enabled', 'cipher aes_256 enabled'],
            ['a dimension pair', 'resize scale_200_200 done', 'resize scale_200_200 done'],
            ['an ordinal', 'parsed line_1 of input', 'parsed line_1 of input'],
            ['digits running into letters', 'waited tick_1234ms total', 'waited tick_1234ms total'],
            [
                'digits running into a snake_case word',
                'opened team_190219_stripe folder',
                'opened team_190219_stripe folder',
            ],
            [
                'a hex group of an underscore-joined uuid, which ends in a letter',
                'copying team_01a1116e_7b83_0000_0ed6_45f0bfe69515 now',
                'copying team_01a1116e_7b83_0000_0ed6_45f0bfe69515 now',
            ],
        ])('snakenum does not claim %s', (_name, input, expected) => {
            expect(maskString(input).masked).toEqual(expected)
        })

        // The hex rule needs a letter, which is what keeps its 8-char floor off plain numbers. Without
        // the letter, every id, epoch, and byte count of 8 or more digits would read as `<HEX>`.
        it.each([
            ['a short digit run stays a number', 'offset 1724495000 read', 'offset <N> read'],
            ['a long digit run stays a number', 'id 1234567890123456 seen', 'id <N> seen'],
            ['a hex run under the floor is left alone', 'code abc12 seen', 'code abc12 seen'],
            ['a hex run inside an identifier is left alone', 'key deadbeef_1 seen', 'key deadbeef_1 seen'],
        ])('hex letter requirement: %s', (_name, input, expected) => {
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
                clftime: 0,
                ctime: 0,
                httpdate: 0,
                syslogtime: 0,
                id: 0,
                stripeid: 0,
                snakeuuid: 0,
                uuid: 0,
                snakenum: 0,
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

            it('masks keys, so a value-shaped key becomes its placeholder', () => {
                expect(patternOf('{"10.0.0.1":1,"7141":2,"user@example.com":3}')).toEqual('<JSON:<EMAIL>,<IP>,<N>>')
            })

            it('deduplicates masked keys, so an object keyed by data is one key wide', () => {
                const body = JSON.stringify(
                    Object.fromEntries(Array.from({ length: 50 }, (_unused, index) => [`10.0.0.${index}`, 1]))
                )
                // Deduplicating before the cap is what drops the overflow suffix too: a `+18` here
                // would carry the raw key count back into the pattern.
                expect(patternOf(body)).toEqual('<JSON:<IP>>')
            })

            it('counts key masking in the rule fires, so the rule metric still matches what shipped', () => {
                const ipv4 = MASK_RULES.findIndex((rule) => rule.name === 'ipv4')
                expect(patternResult('{"10.0.0.1":1,"10.0.0.2":2}').ruleFires[ipv4]).toEqual(2)
            })
        })
    })

    describe('PATTERN_VERSION ratchet', () => {
        /**
         * Bodies chosen to reach every branch that decides a pattern's shape: each mask rule, the
         * message keys, the key-set and array forms, both caps, and the order of parse and cap.
         *
         * The message-key bodies are derived from `MESSAGE_KEYS` so a new key joins the corpus, and
         * moves the digest, on arrival. Mask rules cannot be derived that way, so a coverage test
         * below holds the equivalent line for them.
         */
        const CORPUS: (string | null)[] = [
            null,
            '',
            'started at 2026-08-24T10:20:45.123Z ok',
            'I0827 11:39:40.307946 1 proxier.go:1484] reloading',
            'W0101 00:00:00 rotate E0102 01:02:03 retry F0103 02:03:04 exit',
            '10.0.0.1 - - [02/Jan/2026:03:04:05 +0000] "GET /a" 200',
            'booted Mon Jan  2 03:04:05 UTC 2026, expires Mon, 02 Jan 2026 04:05:06 GMT',
            'Jan  2 03:04:05 host sshd: accepted',
            'request 0f2d6faf-07e3-4cff-bf47-7efa1024aee2 took 7141ms',
            'mail ops@example.com via api.example.com at 10.0.0.7 slot 0xdeadbeef',
            'checksum deadbeefdeadbeef00 verified',
            'built sha a3f9c1d2 from 1724495000',
            'charging cus_Qz4WmTb7Kx9pLr for org_01ABCDEF23GHJK45MNPQRS67',
            'renewing sub_QzWmTbKxRpLvNa for team_190219 job_12345678-07e3-4cff-bf47-7efa1024aee2',
            'export job_1234_01905063-07e3-4cff-bf47-7efa1024aee2 done',
            '{"10.0.0.1":1,"10.0.0.2":2}',
            ...MESSAGE_KEYS.map((key) => JSON.stringify({ [key]: 'served 3 requests', level: 'info' })),
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
            4: '357baaab19f622df',
            5: '130ce70d5eeff09e',
            6: '9cb90c3c0ef4135a',
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
            messageKeys: MESSAGE_KEYS,
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

    describe('property sweeps', () => {
        // Seeded, so a failing input reproduces.
        const mulberry32 = (seed: number) => (): number => {
            seed = (seed + 0x6d2b79f5) | 0
            let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296
        }
        const pick = <T>(rand: () => number, items: readonly T[]): T => items[Math.floor(rand() * items.length)]
        const chars = (rand: () => number, alphabet: string, min: number, max: number): string =>
            Array.from({ length: min + Math.floor(rand() * (max - min + 1)) }, () => pick(rand, [...alphabet])).join('')
        const LOWER = 'abcdefghijklmnopqrstuvwxyz'
        const UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        const DIGITS = '0123456789'

        const sequentialChain = (input: string): string =>
            MASK_RULES.reduce((acc, rule) => acc.replace(new RE2(rule.pattern, 'g'), rule.replacement), input)

        // `notBefore` and `notAfter` skip joins where `id`, `email`, `host`, `hex0x` and `hex` already
        // disagree with the chain in v5, so the sweeps test only the new rules.
        type Fragment = { text: string; notBefore: string; notAfter?: string }
        const fragment = (rand: () => number): Fragment =>
            pick(rand, [
                () => ({ text: '2026-08-24T10:20:45.123Z', notBefore: '' }),
                () => ({ text: 'I0827 11:39:40.307946', notBefore: '' }),
                () => ({ text: `${chars(rand, LOWER, 1, 3)}@example.com`, notBefore: '.-' }),
                () => ({
                    text: `${chars(rand, LOWER, 2, 6)}_${chars(rand, UPPER, 1, 1)}${chars(rand, LOWER + DIGITS, 3, 8)}9`,
                    notBefore: '-',
                }),
                () => ({ text: `cus_${chars(rand, UPPER, 1, 1)}${chars(rand, LOWER + UPPER, 13, 13)}`, notBefore: '' }),
                () => ({ text: `sub_${chars(rand, UPPER, 1, 1)}${chars(rand, LOWER + UPPER, 23, 23)}`, notBefore: '' }),
                () => {
                    const hex = pick(rand, ['0123456789abcdef', '0123456789ABCDEF', DIGITS])
                    const uuid = [8, 4, 4, 4, 12].map((length) => chars(rand, hex, length, length)).join('-')
                    const glued = chars(rand, DIGITS + 'abcdef', 0, 6)
                    const chain = pick(rand, [
                        '',
                        `_${chars(rand, DIGITS, 4, 8)}`,
                        `_${chars(rand, DIGITS, 4, 8)}_${chars(rand, DIGITS, 1, 4)}`,
                    ])
                    return {
                        text: glued || chain ? `${chars(rand, LOWER, 1, 4)}${chain}_${glued}${uuid}` : uuid,
                        notBefore: '',
                    }
                },
                () => ({ text: `${chars(rand, LOWER, 1, 4)}.example.io`, notBefore: '', notAfter: '.-' }),
                () => ({ text: '0xdeadbeef', notBefore: '_' }),
                () => ({ text: 'deadbeefdeadbeef00', notBefore: '' }),
                () => ({ text: '10.0.0.1', notBefore: '' }),
                () => ({ text: chars(rand, DIGITS, 1, 20), notBefore: '' }),
                () => ({ text: `${chars(rand, LOWER, 1, 8)}_${chars(rand, DIGITS, 1, 20)}`, notBefore: '' }),
                () => ({
                    text: [6, 4 + Math.floor(rand() * 5), 4 + Math.floor(rand() * 5), 1 + Math.floor(rand() * 3)]
                        .map((length) => chars(rand, DIGITS, length, length))
                        .join('_'),
                    notBefore: '',
                }),
                () => ({ text: chars(rand, LOWER, 1, 8), notBefore: '' }),
            ])()

        const SEPARATORS = [' ', '_', '/', '-', '.', ':', '=', ',']
        const line = (rand: () => number): string => {
            let previous = fragment(rand)
            let out = previous.text
            for (let i = 1 + Math.floor(rand() * 5); i > 0; i--) {
                const next = fragment(rand)
                const allowed = SEPARATORS.filter(
                    (separator) => !previous.notBefore.includes(separator) && !(next.notAfter ?? '').includes(separator)
                )
                out += pick(rand, allowed) + next.text
                previous = next
            }
            return out
        }

        it('masks every generated line the same in one pass as rule by rule', () => {
            const rand = mulberry32(20261016)
            const mismatches: string[] = []
            for (let i = 0; i < 5000 && mismatches.length < 5; i++) {
                const input = line(rand)
                if (maskString(input).masked !== sequentialChain(input)) {
                    mismatches.push(input)
                }
            }
            expect(mismatches).toEqual([])
        })

        it('leaves every masked line unchanged when masked again', () => {
            const rand = mulberry32(20261017)
            const changed: string[] = []
            for (let i = 0; i < 5000 && changed.length < 5; i++) {
                const once = maskString(line(rand)).masked
                if (maskString(once).masked !== once) {
                    changed.push(once)
                }
            }
            expect(changed).toEqual([])
        })

        it('never leaves part of a uuid visible, whatever is glued in front of it', () => {
            const rand = mulberry32(20261020)
            const leaked: string[] = []
            for (let i = 0; i < 20000 && leaked.length < 5; i++) {
                const hex = pick(rand, ['0123456789abcdef', '0123456789ABCDEF', DIGITS])
                const groups = [8, 4, 4, 4, 12].map((length) => chars(rand, hex, length, length))
                const prefix = Array.from({ length: Math.floor(rand() * 5) }, () =>
                    pick(rand, [
                        () => chars(rand, LOWER, 1, 6),
                        () => `_${chars(rand, DIGITS, 1, 14)}`,
                        () => `_${chars(rand, '0123456789abcdef', 1, 14)}`,
                        () => chars(rand, DIGITS, 1, 14),
                        () => chars(rand, '0123456789abcdef', 1, 14),
                        () => pick(rand, [' ', '/', '.', ':', '=', ',', '_']),
                    ])()
                ).join('')
                const input = `${prefix}${groups.join('-')} ok`
                const masked = maskString(input).masked
                if (groups.slice(1).some((group) => masked.includes(`${group}-`) || masked.includes(`-${group}`))) {
                    leaked.push(input)
                }
            }
            expect(leaked).toEqual([])
        })

        it('masks a digit run after an underscore only at 4 digits or more', () => {
            const rand = mulberry32(20261018)
            const wrong: string[] = []
            for (let i = 0; i < 5000 && wrong.length < 5; i++) {
                const word = chars(rand, LOWER, 1, 10)
                const digits = chars(rand, DIGITS, 1, 20)
                const after = pick(rand, [' ', '/', '-', '.', ':', ',', 'ms', '_stripe', 'a'])
                const input = `x ${word}_${digits}${after} y`
                const partOfName = /^[A-Za-z_]/.test(after)
                const expected = digits.length >= 4 && !partOfName ? `x ${word}_<N>${after} y` : input
                if (maskString(input).masked !== expected) {
                    wrong.push(input)
                }
            }
            expect(wrong).toEqual([])
        })

        it('masks a body of letters only behind cus_ or sub_, at 14 or 24 letters led by an uppercase letter', () => {
            const rand = mulberry32(20261019)
            const wrong: string[] = []
            for (let i = 0; i < 5000 && wrong.length < 5; i++) {
                const body = chars(rand, LOWER + UPPER, 8, 30)
                const prefix = pick(rand, ['cus', 'sub', chars(rand, LOWER, 2, 4)])
                const input = `x ${prefix}_${body} y`
                const isId =
                    ['cus', 'sub'].includes(prefix) &&
                    (body.length === 14 || body.length === 24) &&
                    UPPER.includes(body[0])
                if (maskString(input).masked !== (isId ? 'x <ID> y' : input)) {
                    wrong.push(input)
                }
            }
            expect(wrong).toEqual([])
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
            // A weekday form and the month form overlap: the chain would let `syslogtime` cut the
            // line first and strand the weekday, unless the weekday rules are listed ahead of it.
            'Mon Jan  2 03:04:05 UTC 2026 boot complete',
            'expires Mon, 02 Jan 2026 03:04:05 GMT',
            '10.0.0.1 - - [02/Jan/2026:03:04:05 +0000] "GET /v0/export" 200 35',
            'Jan  2 03:04:05 host sshd: accepted from 10.0.0.1',
            'built sha a3f9c1d2 at 1724495000 into deadbeefdeadbeef00',
            'charging cus_Qz4WmTb7Kx9pLr for user_2KpXr8ZmTq5NvBw7Ld3Cjs',
            // An uppercase UUID behind a prefix: `id` and `uuid` both match, so the chain must run `id` first.
            'trace_0A1B2C3D-4E5F-6789-ABCD-EF0123456789 started',
            // An id-shaped local part: `id` and `email` match at one offset, so the chain must run `email` first.
            'john_D2oe@example.com sent',
            // `snakenum` starts before `uuid` here, so the chain must run `snakeuuid` ahead of both.
            'job_12345678-07e3-4cff-bf47-7efa1024aee2 queued',
            'export job_1234_01905063-07e3-4cff-bf47-7efa1024aee2 done',
            'No active replica has part 202610_4682747_4682751_2 for ops_12345@example.com',
            'GET /v1/customers/cus_TjuwpGlQcCSDCk then shard_1234.example.com then x86_64',
        ]

        it.each(corpus.map((line) => [line] as const))('%s', (line) => {
            expect(maskString(line).masked).toEqual(sequentialChain(line))
        })
    })
})
