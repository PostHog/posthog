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

    it('decodes every valid JSON encoding of every UTF-16 code unit back to that unit', () => {
        const mismatches: string[] = []
        for (let unit = 0; unit <= 0xffff; unit++) {
            const char = String.fromCharCode(unit)
            const encodings = [JSON.stringify(char), `"\\u${unit.toString(16).padStart(4, '0')}"`]
            if (unit >= 0x20 && char !== '"' && char !== '\\') {
                encodings.push(`"${char}"`)
            }
            for (const encoded of encodings) {
                if (decodeLogAttributeValue(encoded) !== char) {
                    mismatches.push(encoded)
                }
            }
        }
        expect(mismatches).toEqual([])
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
