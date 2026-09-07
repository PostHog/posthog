/**
 * The HogQL parser counts characters, Monaco counts UTF-16 code units.
 *
 * They agree until a query holds a character outside the Basic Multilingual Plane. An emoji is one
 * character to Python and two code units to Monaco, so every offset after it points one unit short
 * per emoji, and a marker or a replacement lands in the wrong place.
 *
 * Convert against the exact text the offset was measured in, which is the statement the server
 * analyzed rather than the whole editor, then add that statement's own offset.
 */
export function characterOffsetToUtf16(text: string, characterOffset: number): number {
    let utf16Offset = 0
    let characters = 0
    while (characters < characterOffset && utf16Offset < text.length) {
        // A code point above 0xffff is stored as a surrogate pair, which is two units to Monaco.
        utf16Offset += (text.codePointAt(utf16Offset) ?? 0) > 0xffff ? 2 : 1
        characters += 1
    }
    return utf16Offset
}
