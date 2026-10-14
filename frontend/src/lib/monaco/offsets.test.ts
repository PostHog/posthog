import { characterOffsetToUtf16 } from './offsets'

describe('characterOffsetToUtf16', () => {
    const QUERY = "SELECT '😀', count() FROM events WHERE properties.$browser_version = 120"

    it('leaves offsets untouched when every character is one code unit', () => {
        const plain = 'SELECT 1 FROM events'
        expect(characterOffsetToUtf16(plain, 7)).toBe(7)
    })

    it('shifts an offset that follows an emoji so it selects the intended text', () => {
        // The parser reports the literal at its character offset; reading that offset as UTF-16
        // selects ' 12' instead of '120', so a replacement produces ='120'0.
        const characterOffset = Array.from(QUERY).indexOf('1')
        const utf16Offset = characterOffsetToUtf16(QUERY, characterOffset)

        expect(QUERY.slice(characterOffset, characterOffset + 3)).toBe(' 12')
        expect(QUERY.slice(utf16Offset, utf16Offset + 3)).toBe('120')
    })

    it.each([
        ['before the emoji', 3],
        ['at the emoji', 8],
        ['after two emoji', 12],
    ])('round-trips a character offset %s', (_name: string, characterOffset: number) => {
        const text = "a😀b😀c '120'"
        const characters = Array.from(text)
        const utf16Offset = characterOffsetToUtf16(text, characterOffset)

        expect(text.slice(utf16Offset)).toBe(characters.slice(characterOffset).join(''))
    })

    it('clamps an offset past the end of the text', () => {
        expect(characterOffsetToUtf16('abc', 99)).toBe(3)
    })
})
