import { RE2JS } from 're2js'

import { formatRE2Error } from './regexp'

describe('RE2 Regex Validation', () => {
    describe('formatRE2Error', () => {
        it('formats errors with helpful context for lookahead assertions', () => {
            try {
                RE2JS.compile('(?=test)')
            } catch (error) {
                const message = formatRE2Error(error as Error, '(?=test)')
                expect(message).toContain('Lookahead and lookbehind')
            }
        })

        it('formats errors with helpful context for backreferences', () => {
            try {
                RE2JS.compile('(.)\\1')
            } catch (error) {
                const message = formatRE2Error(error as Error, '(.)\\1')
                expect(message).toContain('Backreferences')
            }
        })

        it('formats errors with helpful context for possessive quantifiers', () => {
            try {
                RE2JS.compile('\\w++')
            } catch (error) {
                const message = formatRE2Error(error as Error, '\\w++')
                expect(message).toContain('Possessive quantifiers')
            }
        })

        it('formats errors with helpful context for unclosed brackets', () => {
            try {
                RE2JS.compile('[A-Z')
            } catch (error) {
                const message = formatRE2Error(error as Error, '[A-Z')
                expect(message).toContain('Check that all brackets and parentheses are properly closed')
            }
        })
    })
})
