const SEPARATOR = /[\t\n\f\r /]*/y
const ATTRIBUTE =
    /([^\t\n\f\r />][^\t\n\f\r />=]*)(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:"([^"]*)"?|'([^']*)'?|([^\t\n\f\r >]*)))?/y

export const asciiLowerCase = (text: string): string => text.replace(/[A-Z]+/g, (upper) => upper.toLowerCase())

export type Attribute = { name: string; value: string | null; start: number; end: number }

export type OpeningTag = { attributes: Attribute[]; end: number; selfClosing: boolean }

export const readOpeningTag = (html: string, attributesStart: number, collect = true): OpeningTag => {
    const attributes: Attribute[] = []
    let lastAttributeEnd = attributesStart
    for (let position = attributesStart; ; ) {
        SEPARATOR.lastIndex = position
        SEPARATOR.test(html)
        const start = SEPARATOR.lastIndex
        if (html[start] === '>') {
            return { attributes, end: start, selfClosing: html[start - 1] === '/' && lastAttributeEnd < start }
        }
        ATTRIBUTE.lastIndex = start
        const match = ATTRIBUTE.exec(html)
        if (!match) {
            return { attributes, end: -1, selfClosing: false }
        }
        lastAttributeEnd = ATTRIBUTE.lastIndex
        if (collect) {
            const value = match[2] ?? match[3] ?? (match[4] || null)
            attributes.push({ name: asciiLowerCase(match[1]), value, start, end: lastAttributeEnd })
        }
        position = lastAttributeEnd
    }
}

export const readOpeningTagOrCut = (tag: string, attributesStart: number): OpeningTag => {
    const read = readOpeningTag(tag, attributesStart)
    const cut = read.end === -1 ? tag.indexOf('>', attributesStart) : -1
    if (cut === -1) {
        return read
    }
    const { attributes, selfClosing } = readOpeningTag(tag.slice(0, cut + 1), attributesStart)
    return { attributes: attributes.filter(({ end }) => end <= cut), end: cut, selfClosing }
}
