const HTML_ESCAPE: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
}

const ESCAPE_GROWTH_BY_CHAR_CODE: ReadonlyMap<number, number> = new Map(
    Object.entries(HTML_ESCAPE).map(([character, escaped]) => [character.charCodeAt(0), escaped.length - 1])
)

// Covers `& < > " '`, which is enough for a text node and for a quoted attribute value.
export const escapeHtml = (text: string): string => text.replace(/[&<>"']/g, (c) => HTML_ESCAPE[c])

export const escapedHtmlByteLength = (text: string): number => {
    let growth = 0
    for (let index = 0; index < text.length; index++) {
        growth += ESCAPE_GROWTH_BY_CHAR_CODE.get(text.charCodeAt(index)) ?? 0
    }
    return Buffer.byteLength(text, 'utf8') + growth
}
