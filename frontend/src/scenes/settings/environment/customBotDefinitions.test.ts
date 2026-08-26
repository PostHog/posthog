import { CustomBotDefinition, CustomBotMatcher } from '~/queries/schema/schema-general'

import { matchesUserAgent, validateCustomBotDefinition } from './customBotDefinitions'

const definition = (overrides: Partial<CustomBotDefinition> = {}): CustomBotDefinition => ({
    id: '1',
    name: 'Acme scraper',
    pattern: 'AcmeBot',
    matcher: CustomBotMatcher.Contains,
    ...overrides,
})

describe('customBotDefinitions', () => {
    // These rules mirror the ones the API enforces. When they drift, saving returns a 400 with no
    // indication of which row caused it.
    describe('validateCustomBotDefinition', () => {
        test.each([
            ['empty name', { name: '' }, 'Give this bot a name.'],
            ['empty pattern', { pattern: '  ' }, 'Add a user agent to match.'],
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
        ])('rejects %s', (_name, overrides, expected) => {
            expect(validateCustomBotDefinition(definition(overrides))).toEqual(expected)
        })

        test.each([
            ['a plain substring', {}],
            ['a substring with regex metacharacters', { pattern: 'Acme (bot) v1.0' }],
            ['an anchored regex', { pattern: '^AcmeBot/[0-9]+$', matcher: CustomBotMatcher.Regex }],
        ])('accepts %s', (_name, overrides) => {
            expect(validateCustomBotDefinition(definition(overrides))).toBeNull()
        })
    })

    describe('matchesUserAgent', () => {
        // The backend compiles a substring pattern with (?i), so the tester has to be
        // case-insensitive too or it tells people the wrong thing.
        test.each([
            ['same case', 'AcmeBot/1.0', true],
            ['different case', 'acmebot/1.0', true],
            ['no match', 'Mozilla/5.0', false],
        ])('substring matching, %s', (_name, userAgent, expected) => {
            expect(matchesUserAgent(definition(), userAgent)).toBe(expected)
        })

        it('treats a substring pattern as a literal, not a regex', () => {
            const literal = definition({ pattern: 'Acme.Bot' })

            expect(matchesUserAgent(literal, 'Acme.Bot')).toBe(true)
            expect(matchesUserAgent(literal, 'AcmeXBot')).toBe(false)
        })

        it('matches with a regex pattern', () => {
            const regex = definition({ pattern: 'AcmeBot/[0-9]+', matcher: CustomBotMatcher.Regex })

            expect(matchesUserAgent(regex, 'AcmeBot/12')).toBe(true)
            expect(matchesUserAgent(regex, 'AcmeBot/vNext')).toBe(false)
        })
    })
})
