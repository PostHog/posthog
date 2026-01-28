import { RE2JS } from 're2js'

import { formatRE2Error } from './regexp'

describe('RE2 Regex Validation', () => {
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
