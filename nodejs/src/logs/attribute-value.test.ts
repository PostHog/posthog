import { decodeLogAttributeValue, encodeLogAttributeValue } from './attribute-value'

describe('decodeLogAttributeValue', () => {
    it.each([
        ['plain quoted string', '"error"', 'error'],
        ['empty quoted string', '""', ''],
        ['quoted number-like string', '"3"', '3'],
        ['unquoted value passes through', 'error', 'error'],
        ['unquoted number passes through', '123', '123'],
        ['single leading quote only', '"error', '"error'],
        ['single trailing quote only', 'error"', 'error"'],
        ['too short to be quoted', '"', '"'],
        ['escaped quote inside', '"say \\"hi\\""', 'say "hi"'],
        ['escaped backslash inside', '"a\\\\b"', 'a\\b'],
        ['unicode escape', '"\\u0041BC"', 'ABC'],
        ['newline escape', '"a\\nb"', 'a\nb'],
        ['invalid JSON quoted value passes through', '"unterminated\\', '"unterminated\\'],
        ['quoted-but-invalid JSON passes through as-is', '"a"b"', '"a"b"'],
        ['multibyte content', '"héllo wörld"', 'héllo wörld'],
        ['quoted JSON-looking string', '"{\\"a\\":1}"', '{"a":1}'],
    ])('%s', (_name, input, expected) => {
        expect(decodeLogAttributeValue(input)).toBe(expected)
    })

    it('matches JSON.parse semantics on quoted strings', () => {
        const cases = ['"error"', '"3"', '"a\\nb"', '"\\u0041"', '"say \\"hi\\""', '"a\\\\b"', '""']
        for (const input of cases) {
            // oxlint-disable-next-line eslint-js/no-restricted-syntax
            expect(decodeLogAttributeValue(input)).toBe(JSON.parse(input))
        }
    })
})

describe('encodeLogAttributeValue', () => {
    it.each([
        ['plain string is JSON-encoded', 'error', '"error"'],
        ['already-encoded string passes through', '"error"', '"error"'],
        ['number passes through', '123', '123'],
        ['boolean passes through', 'true', 'true'],
        ['object passes through', '{"a":1}', '{"a":1}'],
    ])('%s', (_name, input, expected) => {
        expect(encodeLogAttributeValue(input)).toBe(expected)
    })
})
