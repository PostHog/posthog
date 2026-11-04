import { RE2JS } from 're2js'

import { formatRE2Error, getLoadedRE2, isValidRE2 } from './regexp'

describe('RE2 Regex Validation', () => {
    describe('isValidRE2', () => {
        it.each([
            { pattern: '^/api/.*', expected: true },
            { pattern: '(?=lookahead)', expected: false },
            { pattern: '[unclosed', expected: false },
        ])('returns $expected for $pattern once the engine loads', async ({ pattern, expected }) => {
            expect(await isValidRE2(pattern)).toBe(expected)
            expect(getLoadedRE2()).toBe(RE2JS)
        })
    })

    describe('formatRE2Error', () => {
        it.each([
            { pattern: '(?=test)', expectedSubstring: 'Lookahead and lookbehind' },
            { pattern: '(.)\\1', expectedSubstring: 'Backreferences' },
            { pattern: '\\w++', expectedSubstring: 'Possessive quantifiers' },
            { pattern: '[A-Z', expectedSubstring: 'Check that all brackets and parentheses are properly closed' },
        ])('formats errors with helpful context for $pattern', ({ pattern, expectedSubstring }) => {
            let errorThrown = false
            try {
                RE2JS.compile(pattern)
            } catch (error) {
                errorThrown = true
                const message = formatRE2Error(error as Error, pattern)
                expect(message).toContain(expectedSubstring)
            }
            expect(errorThrown).toBe(true)
        })
    })
})
