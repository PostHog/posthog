import { CustomBotDefinition, CustomBotField, CustomBotMatcher } from '~/queries/schema/schema-general'

import { matchesValue, validateCustomBotDefinition } from './customBotDefinitionsUtils'

const definition = (overrides: Partial<CustomBotDefinition> = {}): CustomBotDefinition => ({
    id: '1',
    name: 'Acme scraper',
    key: CustomBotField.RawUserAgent,
    pattern: 'AcmeBot',
    matcher: CustomBotMatcher.Contains,
    ...overrides,
})

const ipRule = (pattern: string): CustomBotDefinition =>
    definition({ key: CustomBotField.IP, matcher: CustomBotMatcher.Cidr, pattern })

describe('customBotDefinitionsUtils', () => {
    // These rules mirror the ones the API enforces. When they drift, a rule the editor calls valid
    // comes back as a 400 on save instead of an inline error next to the row.
    describe('validateCustomBotDefinition', () => {
        test.each([
            ['empty name', { name: '' }, 'Give this bot a name.'],
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
                { matcher: CustomBotMatcher.Cidr, pattern: '192.0.2.0/24' },
                'Ranges only work with the IP address property.',
            ],
        ])('rejects %s', (_name, overrides, expected) => {
            expect(validateCustomBotDefinition(definition(overrides))).toEqual(expected)
        })

        test.each([
            ['a bare address', '192.0.2.7'],
            ['a v4 range', '192.0.2.0/24'],
            ['a v6 range', '2001:db8::/32'],
            ['host bits set', '192.0.2.7/24'],
        ])('accepts %s', (_name, pattern) => {
            expect(validateCustomBotDefinition(ipRule(pattern))).toBeNull()
        })

        test.each([
            ['a hostname', 'not-an-ip'],
            ['an octet over 255', '192.0.2.999'],
            // Python's ipaddress rejects leading zeros, so the tester must too or Save 400s.
            ['a leading-zero octet', '192.168.001.1'],
            ['a prefix wider than the family', '192.0.2.0/33'],
            ['too many parts', '192.0.2.0/24/8'],
        ])('rejects %s as a range', (_name, pattern) => {
            expect(validateCustomBotDefinition(ipRule(pattern))).toEqual('This is not a valid IP address or range.')
        })

        test.each([
            ['a plain substring', {}],
            ['a substring with regex metacharacters', { pattern: 'Acme (bot) v1.0' }],
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
            expect(validateCustomBotDefinition(definition(overrides))).toBeNull()
        })
    })

    describe('matchesValue', () => {
        // The backend compiles a substring pattern with (?i), so the tester has to be
        // case-insensitive too or it tells people the wrong thing.
        test.each([
            ['same case', 'AcmeBot/1.0', true],
            ['different case', 'acmebot/1.0', true],
            ['no match', 'Mozilla/5.0', false],
        ])('substring matching, %s', (_name, value, expected) => {
            expect(matchesValue(definition(), value)).toBe(expected)
        })

        it('treats a substring pattern as a literal, not a regex', () => {
            const literal = definition({ pattern: 'Acme.Bot' })

            expect(matchesValue(literal, 'Acme.Bot')).toBe(true)
            expect(matchesValue(literal, 'AcmeXBot')).toBe(false)
        })

        it('matches with a regex pattern', () => {
            const regex = definition({ pattern: 'AcmeBot/[0-9]+', matcher: CustomBotMatcher.Regex })

            expect(matchesValue(regex, 'AcmeBot/12')).toBe(true)
            expect(matchesValue(regex, 'AcmeBot/vNext')).toBe(false)
        })

        it('applies stacked leading flag groups when matching', () => {
            const regex = definition({ pattern: '(?i)(?s)acme.bot', matcher: CustomBotMatcher.Regex })

            expect(matchesValue(regex, 'ACME\nBOT')).toBe(true)
            expect(matchesValue(regex, 'GlobexBot')).toBe(false)
        })

        it('applies a leading (?i) flag so a case-insensitive rule matches', () => {
            // ClickHouse regex matching is case-sensitive by default, so (?i) is the natural way to
            // write one. new RegExp rejects the inline group, so without translation this reports no match.
            const regex = definition({ pattern: '(?i)acmebot', matcher: CustomBotMatcher.Regex })

            expect(matchesValue(regex, 'ACMEBOT/1.0')).toBe(true)
            expect(matchesValue(regex, 'Mozilla/5.0')).toBe(false)
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
        ])('range matching, %s', (_name, pattern, value, expected) => {
            expect(matchesValue(ipRule(pattern), value)).toBe(expected)
        })

        it('does not match when the value is not an address', () => {
            expect(matchesValue(ipRule('192.0.2.0/24'), 'not-an-ip')).toBe(false)
        })
    })
})
