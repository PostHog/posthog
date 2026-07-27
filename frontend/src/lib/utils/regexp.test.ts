import { RE2JS } from 're2js'

import { formatRE2Error, hasRegexEscape } from './regexp'

describe('RE2 Regex Validation', () => {
    describe('hasRegexEscape', () => {
        it.each([
            // Regex escapes typed into a plain-substring filter, the case that silently no-ops.
            { value: 'terra\\.security', expected: true },
            { value: 'foo\\+bar', expected: true },
            { value: 'a\\(b\\)', expected: true },
            // Plain values, including Windows paths, must not trip the warning.
            { value: 'terra.security', expected: false },
            { value: 'C:\\Users\\me', expected: false },
            { value: 'hello world', expected: false },
        ])('returns $expected for "$value"', ({ value, expected }) => {
            expect(hasRegexEscape(value)).toBe(expected)
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
