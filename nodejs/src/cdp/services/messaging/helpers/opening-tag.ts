const SEPARATOR = /[\t\n\f\r /]*/y
const ATTRIBUTE =
    /([^\t\n\f\r />][^\t\n\f\r />=]*)(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:"([^"]*)"?|'([^']*)'?|([^\t\n\f\r >]*)))?/y

export type Attribute = { name: string; value: string | null; start: number; end: number }

export type OpeningTag = { attributes: Attribute[]; end: number }

export const readOpeningTag = (html: string, attributesStart: number): OpeningTag => {
    const attributes: Attribute[] = []
    for (let position = attributesStart; ; ) {
        SEPARATOR.lastIndex = position
        SEPARATOR.test(html)
        const start = SEPARATOR.lastIndex
        if (html[start] === '>') {
            return { attributes, end: start }
        }
        ATTRIBUTE.lastIndex = start
        const match = ATTRIBUTE.exec(html)
        if (!match) {
            return { attributes, end: -1 }
        }
        const value = match[2] ?? match[3] ?? (match[4] || null)
        attributes.push({ name: match[1].toLowerCase(), value, start, end: ATTRIBUTE.lastIndex })
        position = ATTRIBUTE.lastIndex
    }
}

export const readOpeningTagOrCut = (tag: string, attributesStart: number): OpeningTag => {
    const read = readOpeningTag(tag, attributesStart)
    const cut = read.end === -1 ? tag.indexOf('>', attributesStart) : -1
    if (cut === -1) {
        return read
    }
    const { attributes } = readOpeningTag(tag.slice(0, cut + 1), attributesStart)
    return { attributes: attributes.filter(({ end }) => end <= cut), end: cut }
}
