import { escapeIdentifier } from '../stl/print'

describe('hogvm print', () => {
    test('escapeIdentifier doubles embedded backticks', () => {
        // The HogQL/Hog parsers only accept a doubled backtick inside a quoted identifier, not a backslash-escaped one.
        expect(escapeIdentifier('a`b')).toBe('`a``b`')
        expect(escapeIdentifier('`')).toBe('````')
    })

    test('escapeIdentifier leaves simple identifiers unquoted', () => {
        expect(escapeIdentifier('normal_id')).toBe('normal_id')
        expect(escapeIdentifier('a b')).toBe('`a b`')
    })
})
