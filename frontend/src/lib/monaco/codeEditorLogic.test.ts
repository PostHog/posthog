import { codePointOffsetToUtf16 } from './codeEditorLogic'

describe('codeEditorLogic', () => {
    describe('codePointOffsetToUtf16', () => {
        const EMOJI_QUERY = "SELECT countIf(event = '🎉') FROM events"

        test.each([
            ['identity without astral characters', 'SELECT 1 FROM events', 20, 20],
            ['start of the text', EMOJI_QUERY, 0, 0],
            ['before the emoji', EMOJI_QUERY, 24, 24],
            ['start of the events reference', EMOJI_QUERY, 33, 34],
            ['end of the query', EMOJI_QUERY, EMOJI_QUERY.length, 40],
        ])('%s', (_name, text, codePointOffset, expected) => {
            expect(codePointOffsetToUtf16(text as string, codePointOffset as number)).toBe(expected)
        })

        it('lands an insertion after the events reference rather than inside it', () => {
            // The parser reports the end of `events` as 39 code points; Monaco holds 40 UTF-16 units.
            const utf16 = codePointOffsetToUtf16(EMOJI_QUERY, 39)

            expect(EMOJI_QUERY.slice(0, utf16)).toBe(EMOJI_QUERY)
            expect(EMOJI_QUERY.slice(0, 39)).not.toBe(EMOJI_QUERY)
        })
    })
})
