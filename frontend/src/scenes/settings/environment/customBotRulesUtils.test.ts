import { CustomBotCondition, CustomBotField, CustomBotMatcher, CustomBotRule } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import {
    conditionMatchesValue,
    ruleMatchesValues,
    parseCustomBotRules,
    sanitizeCustomBotRules,
    validateCustomBotCondition,
    validateCustomBotRule,
    validateCustomBotRuleSet,
    withMatcher,
} from './customBotRulesUtils'

const condition = (overrides: Partial<CustomBotCondition> = {}): CustomBotCondition => ({
    id: 'c1',
    key: CustomBotField.RawUserAgent,
    pattern: 'AcmeBot',
    matcher: CustomBotMatcher.Contains,
    ...overrides,
})

const rule = (overrides: Partial<CustomBotRule> = {}): CustomBotRule => ({
    id: '1',
    name: 'Acme scraper',
    combiner: FilterLogicalOperator.And,
    items: [condition()],
    ...overrides,
})

const ipCondition = (...patterns: string[]): CustomBotCondition =>
    condition({ key: CustomBotField.IP, matcher: CustomBotMatcher.Cidr, pattern: undefined, patterns })

const separateAddresses = (count: number, start = 0): string[] =>
    Array.from({ length: count }, (_, i) => `10.${Math.floor((start + i) / 200)}.${(start + i) % 200}.1`)

const adjacentAddresses = (count: number, start = 0): string[] =>
    Array.from({ length: count }, (_, i) => `10.0.${Math.floor((start + i) / 256)}.${(start + i) % 256}`)

describe('customBotRulesUtils', () => {
    // These rules mirror the ones the API enforces. When they drift, a rule the editor calls valid
    // comes back as a 400 on save instead of an inline error next to the row.
    describe('validateCustomBotCondition', () => {
        test.each([
            ['empty pattern', { pattern: '  ' }, 'Add a value to match.'],
            [
                'lookahead',
                { pattern: 'Acme(?=Bot)', matcher: CustomBotMatcher.Regex },
                'This uses a lookahead, which is not supported here.',
            ],
            [
                'unparsable regex',
                { pattern: 'Acme(', matcher: CustomBotMatcher.Regex },
                'This is not a valid regular expression.',
            ],
            [
                // The server's re.compile rejects (?U), so the editor must too or Save 400s. Only
                // i, m and s are translated to JavaScript flags.
                'a leading inline flag the server rejects',
                { pattern: '(?U)AcmeBot', matcher: CustomBotMatcher.Regex },
                'This is not a valid regular expression.',
            ],
            [
                'a range on a property that is not an IP',
                { matcher: CustomBotMatcher.Cidr, pattern: undefined, patterns: ['192.0.2.0/24'] },
                'Ranges only work with the IP address property.',
            ],
        ])('rejects %s', (_name, overrides, expected) => {
            expect(validateCustomBotCondition(condition(overrides))).toEqual(expected)
        })

        test.each([
            ['a bare address', '192.0.2.7', true],
            ['a v4 range', '192.0.2.0/24', true],
            ['a v6 range', '2001:db8::/32', true],
            ['host bits set', '192.0.2.7/24', true],
            ['an IPv4-mapped address', '::ffff:192.0.2.1', true],
            ['an IPv4-mapped range', '::ffff:192.0.2.0/120', true],
            ['a netmask range', '192.0.2.0/255.255.255.0', true],
            ['a start-end range', '192.0.2.10-192.0.2.40', true],
            ['a start-end range with spaces', '192.0.2.10 - 192.0.2.40', true],
            ['a v6 start-end range', '2001:db8::1-2001:db8::ff', true],
            ['a hostname', 'not-an-ip', false],
            ['an octet over 255', '192.0.2.999', false],
            // Python's ipaddress rejects leading zeros, so the tester must too or Save 400s.
            ['a leading-zero octet', '192.168.001.1', false],
            ['an octal-looking octet', '010.0.0.1', false],
            ['a shortened address', '127.1', false],
            ['a hex octet', '0x7f.0.0.1', false],
            ['a leading-zero octet in an IPv6 address', '::ffff:192.168.001.1', false],
            ['a hex octet in an IPv6 address', '::ffff:0x7f.0.0.1', false],
            ['a prefix wider than the family', '192.0.2.0/33', false],
            ['too many parts', '192.0.2.0/24/8', false],
            ['a netmask with gaps', '192.0.2.0/255.0.255.0', false],
            ['a zone identifier', 'fe80::1%eth0', false],
            ['a start-end range that ends before it starts', '192.0.2.40-192.0.2.10', false],
            ['a start-end range across ip versions', '192.0.2.1-2001:db8::1', false],
        ])('matches the server on %s', (_name, entry, accepted) => {
            expect(validateCustomBotCondition(ipCondition(entry)) === null).toBe(accepted)
        })

        test.each([
            ['no ranges', ipCondition(), 'Add an IP address or range to match.'],
            ['only blank lines', ipCondition('', '  '), 'Add an IP address or range to match.'],
            [
                'one bad entry in a list',
                ipCondition('192.0.2.0/24', 'nope', '2001:db8::/32'),
                "'nope' is not a valid IP address or range.",
            ],
            [
                'a bad entry inside a comma-separated line',
                ipCondition('192.0.2.0/24, 192.0.2.999'),
                "'192.0.2.999' is not a valid IP address or range.",
            ],
            [
                'a start-end range that ends before it starts',
                ipCondition('192.0.2.40-192.0.2.10'),
                "In '192.0.2.40-192.0.2.10', the start comes after the end.",
            ],
            ['too many ranges', ipCondition(...separateAddresses(501)), 'A condition can have at most 500 IP ranges.'],
            [
                'ranges that split into too many network blocks',
                ipCondition(...Array.from({ length: 126 }, (_, n) => `10.0.${n}.1-10.0.${n}.6`)),
                'These ranges cover more than 500 network blocks. Use fewer or wider ranges.',
            ],
        ])('rejects %s', (_name, value, expected) => {
            expect(validateCustomBotCondition(value)).toEqual(expected)
        })

        test.each([
            ['a plain substring', {}],
            ['a substring with regex metacharacters', { pattern: 'Acme (bot) v1.0' }],
            [
                'an equality on a number',
                { key: CustomBotField.ScreenWidth, matcher: CustomBotMatcher.Exact, pattern: '800' },
            ],
            ['an anchored regex', { pattern: '^AcmeBot/[0-9]+$', matcher: CustomBotMatcher.Regex }],
            // The server and ClickHouse accept a leading inline flag group; JavaScript RegExp does
            // not, so these would wrongly block Save without the flag translation.
            ['a leading case-insensitive flag', { pattern: '(?i)(acme|globex)bot', matcher: CustomBotMatcher.Regex }],
            ['leading multiline and dotall flags', { pattern: '(?ms)^Acme.Bot', matcher: CustomBotMatcher.Regex }],
            // Python also accepts stacked and repeated flag groups; RegExp rejects both a leftover
            // (?s) group in the body and a doubled letter in the flags argument.
            ['stacked leading flag groups', { pattern: '(?i)(?s)acme.bot', matcher: CustomBotMatcher.Regex }],
            ['a repeated flag letter', { pattern: '(?ii)acmebot', matcher: CustomBotMatcher.Regex }],
        ])('accepts %s', (_name, overrides) => {
            expect(validateCustomBotCondition(condition(overrides))).toBeNull()
        })
    })

    describe('validateCustomBotRule', () => {
        test.each([
            ['an empty name', rule({ name: '' }), 'Give this bot a name.'],
            ['no conditions', rule({ items: [] }), 'Add at least one condition.'],
            ['an unusable condition', rule({ items: [condition({ pattern: '' })] }), 'Add a value to match.'],
            [
                // Dragging a condition into a rule can exceed the cap without the add button.
                'too many conditions',
                rule({ items: Array.from({ length: 11 }, (_, i) => condition({ id: String(i) })) }),
                'A rule can have at most 10 conditions.',
            ],
        ])('rejects %s', (_name, value, expected) => {
            expect(validateCustomBotRule(value)).toEqual(expected)
        })

        it('accepts a usable rule', () => {
            expect(validateCustomBotRule(rule())).toBeNull()
        })
    })

    describe('validateCustomBotRuleSet', () => {
        // The per-rule cap cannot see siblings, so a set over the aggregate budget would save as
        // valid in the editor and 400 on the server without this mirror.
        it('rejects a set over the aggregate condition budget', () => {
            const rules = Array.from({ length: 11 }, (_, i) =>
                rule({
                    id: String(i),
                    items: Array.from({ length: 10 }, (_, j) => condition({ id: `${i}-${j}` })),
                })
            )

            expect(validateCustomBotRuleSet(rules)).toEqual('You can have at most 100 conditions across all rules.')
            expect(validateCustomBotRuleSet(rules.slice(0, 10))).toBeNull()
        })

        it('rejects a set over the aggregate IP range budget', () => {
            const rules = Array.from({ length: 3 }, (_, i) =>
                rule({ id: String(i), items: [ipCondition(...separateAddresses(400, i * 400))] })
            )

            expect(validateCustomBotRuleSet(rules)).toEqual(
                'You can have at most 1000 IP network blocks across all rules.'
            )
            expect(validateCustomBotRuleSet(rules.slice(0, 2))).toBeNull()
        })

        it('counts adjacent addresses as the network blocks they merge into', () => {
            const rules = Array.from({ length: 3 }, (_, i) =>
                rule({ id: String(i), items: [ipCondition(...adjacentAddresses(400, i * 400))] })
            )

            expect(validateCustomBotRuleSet(rules)).toBeNull()
        })
    })

    describe('conditionMatchesValue', () => {
        // The backend compiles a substring pattern with (?i), so the tester has to be
        // case-insensitive too or it tells people the wrong thing.
        test.each([
            ['same case', 'AcmeBot/1.0', true],
            ['different case', 'acmebot/1.0', true],
            ['no match', 'Mozilla/5.0', false],
        ])('substring matching, %s', (_name, value, expected) => {
            expect(conditionMatchesValue(condition(), value)).toBe(expected)
        })

        it('treats a substring pattern as a literal, not a regex', () => {
            const literal = condition({ pattern: 'Acme.Bot' })

            expect(conditionMatchesValue(literal, 'Acme.Bot')).toBe(true)
            expect(conditionMatchesValue(literal, 'AcmeXBot')).toBe(false)
        })

        // The backend compiles equality to an anchored pattern, so a substring hit must not count.
        test.each([
            ['the exact value', '800', '800', true],
            ['a longer value containing it', '800', '1800', false],
            ['a different case', 'AcmeBot', 'ACMEBOT', false],
        ])('equality matching, %s', (_name, pattern, value, expected) => {
            expect(conditionMatchesValue(condition({ matcher: CustomBotMatcher.Exact, pattern }), value)).toBe(expected)
        })

        it('matches with a regex pattern', () => {
            const regex = condition({ pattern: 'AcmeBot/[0-9]+', matcher: CustomBotMatcher.Regex })

            expect(conditionMatchesValue(regex, 'AcmeBot/12')).toBe(true)
            expect(conditionMatchesValue(regex, 'AcmeBot/vNext')).toBe(false)
        })

        it('applies stacked leading flag groups when matching', () => {
            const regex = condition({ pattern: '(?i)(?s)acme.bot', matcher: CustomBotMatcher.Regex })

            expect(conditionMatchesValue(regex, 'ACME\nBOT')).toBe(true)
            expect(conditionMatchesValue(regex, 'GlobexBot')).toBe(false)
        })

        it('applies a leading (?i) flag so a case-insensitive rule matches', () => {
            // ClickHouse regex matching is case-sensitive by default, so (?i) is the natural way to
            // write one. new RegExp rejects the inline group, so without translation this reports no match.
            const regex = condition({ pattern: '(?i)acmebot', matcher: CustomBotMatcher.Regex })

            expect(conditionMatchesValue(regex, 'ACMEBOT/1.0')).toBe(true)
            expect(conditionMatchesValue(regex, 'Mozilla/5.0')).toBe(false)
        })

        // Subnet membership is the one thing here a person cannot check by eye, so the tester
        // answering it wrongly would be worse than not offering it.
        test.each([
            ['first address in range', '192.0.2.0/24', '192.0.2.0', true],
            ['inside range', '192.0.2.0/24', '192.0.2.55', true],
            ['last address in range', '192.0.2.0/24', '192.0.2.255', true],
            ['just outside range', '192.0.2.0/24', '192.0.3.0', false],
            ['neighbouring range', '192.0.2.0/24', '10.0.2.55', false],
            ['bare address matches itself', '192.0.2.7', '192.0.2.7', true],
            ['bare address rejects another', '192.0.2.7', '192.0.2.8', false],
            ['range written with host bits still matches its network', '192.0.2.7/24', '192.0.2.99', true],
            ['a v6 address inside a v6 range', '2001:db8::/32', '2001:db8:1234::1', true],
            ['a v6 address outside a v6 range', '2001:db8::/32', '2001:dba9::1', false],
            ['a v4 address is not inside a v6 range', '2001:db8::/32', '192.0.2.55', false],
            ['a v6 address is not inside a v4 range', '192.0.2.0/24', '2001:db8::1', false],
            ['an address inside a start-end range', '192.0.2.10-192.0.2.40', '192.0.2.25', true],
            ['the last address of a start-end range', '192.0.2.10-192.0.2.40', '192.0.2.40', true],
            ['an address past a start-end range', '192.0.2.10-192.0.2.40', '192.0.2.41', false],
            ['an address inside a netmask range', '192.0.2.0/255.255.255.0', '192.0.2.55', true],
            ['an IPv4-mapped value inside a v4 range', '192.0.2.0/24', '::ffff:192.0.2.55', true],
            ['a v4 value inside an IPv4-mapped range', '::ffff:192.0.2.0/120', '192.0.2.55', true],
            ['a v4 value outside an IPv4-compatible range', '::192.0.2.0/120', '192.0.2.55', false],
        ])('range matching, %s', (_name, pattern, value, expected) => {
            expect(conditionMatchesValue(ipCondition(pattern), value)).toBe(expected)
        })

        test.each([
            ['the first range', '192.0.2.55', true],
            ['a start-end range later in the list', '198.51.100.25', true],
            ['a v6 range in the list', '2001:db8::5', true],
            ['none of the ranges', '203.0.113.9', false],
        ])('a list of ranges matches %s', (_name, value, expected) => {
            const list = ipCondition('192.0.2.0/24', '198.51.100.10-198.51.100.40, 2001:db8::/32')

            expect(conditionMatchesValue(list, value)).toBe(expected)
        })

        it('does not match when the value is not an address', () => {
            expect(conditionMatchesValue(ipCondition('192.0.2.0/24'), 'not-an-ip')).toBe(false)
        })
    })

    describe('ruleMatchesValues', () => {
        const headless = rule({
            name: 'Headless 800x600',
            items: [
                condition({
                    id: 'w',
                    key: CustomBotField.ScreenWidth,
                    matcher: CustomBotMatcher.Exact,
                    pattern: '800',
                }),
                condition({
                    id: 'h',
                    key: CustomBotField.ScreenHeight,
                    matcher: CustomBotMatcher.Exact,
                    pattern: '600',
                }),
            ],
        })

        // The tester has to combine the way the query does, or it tells people a rule fires when
        // it will not.
        test.each([
            ['AND with both values', FilterLogicalOperator.And, { width: '800', height: '600' }, true],
            ['AND with one value', FilterLogicalOperator.And, { width: '800', height: '768' }, false],
            ['OR with one value', FilterLogicalOperator.Or, { width: '800', height: '768' }, true],
            ['OR with neither value', FilterLogicalOperator.Or, { width: '1024', height: '768' }, false],
        ])('%s', (_name, combiner, values, expected) => {
            expect(
                ruleMatchesValues(
                    { ...headless, combiner },
                    {
                        [CustomBotField.ScreenWidth]: values.width,
                        [CustomBotField.ScreenHeight]: values.height,
                    }
                )
            ).toBe(expected)
        })
    })

    describe('withMatcher', () => {
        test.each([
            [
                'moves a value into the range list',
                condition({ key: CustomBotField.IP, matcher: CustomBotMatcher.Contains, pattern: '192.0.2.7' }),
                CustomBotMatcher.Cidr,
                { pattern: undefined, patterns: ['192.0.2.7'] },
            ],
            [
                'keeps a saved range when the range list is empty',
                condition({
                    key: CustomBotField.IP,
                    matcher: CustomBotMatcher.Cidr,
                    pattern: '192.0.2.0/24',
                    patterns: [],
                }),
                CustomBotMatcher.Cidr,
                { pattern: undefined, patterns: ['192.0.2.0/24'] },
            ],
            [
                'moves the first range back into a value',
                ipCondition('192.0.2.0/24', '198.51.100.0/24'),
                CustomBotMatcher.Exact,
                { pattern: '192.0.2.0/24', patterns: undefined },
            ],
        ])('%s', (_name, value, matcher, expected) => {
            const changed = withMatcher(value, CustomBotField.IP, matcher)

            expect({ pattern: changed.pattern, patterns: changed.patterns }).toEqual(expected)
        })
    })

    describe('sanitizeCustomBotRules', () => {
        it('splits, trims and dedupes a pasted list', () => {
            const pasted = ipCondition('192.0.2.0/24, 198.51.100.0/24', '', ' 192.0.2.10 - 192.0.2.40 ', '192.0.2.0/24')

            const [sanitized] = sanitizeCustomBotRules([rule({ items: [pasted] })])

            expect(sanitized.items).toEqual([
                {
                    id: 'c1',
                    key: CustomBotField.IP,
                    matcher: CustomBotMatcher.Cidr,
                    patterns: ['192.0.2.0/24', '198.51.100.0/24', '192.0.2.10-192.0.2.40'],
                },
            ])
        })
    })

    describe('parseCustomBotRules', () => {
        it('mints deterministic ids so id-less rules do not collapse in the id-keyed editor', () => {
            const raw = [rule({ id: '', name: 'One' }), rule({ id: '', name: 'Two' })]
            const parsed = parseCustomBotRules(raw)

            expect(parsed).toHaveLength(2)
            expect(parsed[0].id).toBeTruthy()
            expect(parsed[0].id).not.toEqual(parsed[1].id)
            // Deterministic ids: a random id would read as an endless unsaved change.
            expect(parseCustomBotRules(raw)).toEqual(parsed)
        })

        it('re-mints colliding ids so rules do not collapse in the id-keyed editor', () => {
            const parsed = parseCustomBotRules([rule({ id: 'dup' }), rule({ id: 'dup', name: 'Second' })])

            expect(parsed).toHaveLength(2)
            expect(parsed[0].id).not.toEqual(parsed[1].id)
        })

        it('re-mints even when an explicit id collides with a fallback id', () => {
            // A stored id can share the fallback shape; the minted replacement must still be unique.
            const parsed = parseCustomBotRules([rule({ id: 'rule-1' }), rule({ id: '', name: 'Second' })])

            const ids = parsed.map((r) => r.id)
            expect(new Set(ids).size).toEqual(ids.length)
        })

        it('keeps parseable rules and drops what does not parse', () => {
            const current = rule()
            const ipList = rule({
                id: '2',
                name: 'Fleet',
                items: [{ ...ipCondition('192.0.2.0/24', '198.51.100.0/24'), id: 'ip1' }],
            })
            const legacyRange = rule({
                id: '3',
                name: 'Office',
                items: [
                    condition({
                        id: 'ip2',
                        key: CustomBotField.IP,
                        matcher: CustomBotMatcher.Cidr,
                        pattern: '192.0.2.0/24',
                    }),
                ],
            })

            // A malformed entry must be dropped, not blind-cast: it would otherwise throw in
            // validation during render and crash the settings scene. An unknown matcher must
            // also drop, or the editor calls valid what the server 400s. A pre-combiner flat
            // entry has no items, so it drops too.
            expect(
                parseCustomBotRules([
                    current,
                    ipList,
                    legacyRange,
                    'garbage',
                    { id: '1', name: 'Flat', key: '$raw_user_agent', matcher: 'contains', pattern: 'AcmeBot' },
                    { id: 'x', items: [{}] },
                    { items: [condition()], name: null },
                    { id: 'y', name: 'n', items: [{ ...condition(), matcher: 'startswith' }] },
                ])
            ).toEqual([
                current,
                ipList,
                {
                    ...legacyRange,
                    items: [
                        {
                            id: 'ip2',
                            key: CustomBotField.IP,
                            matcher: CustomBotMatcher.Cidr,
                            patterns: ['192.0.2.0/24'],
                        },
                    ],
                },
            ])
        })
    })
})
