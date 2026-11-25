const ATTRIBUTE =
    /[\t\n\f\r /]*(?:([^\t\n\f\r />][^\t\n\f\r />=]*)(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:"[^"]*(?:"|$)|'[^']*(?:'|$)|[^\t\n\f\r >]*))?)?/y

export type OpeningTag = {
    attributeNames: string[]
    end: number
}

export const readOpeningTag = (html: string, attributesStart: number): OpeningTag => {
    const attributeNames: string[] = []
    for (let position = attributesStart; ; ) {
        ATTRIBUTE.lastIndex = position
        const name = ATTRIBUTE.exec(html)?.[1]
        if (name) {
            attributeNames.push(name.toLowerCase())
        }
        const next = ATTRIBUTE.lastIndex
        if (html[next] === '>') {
            return { attributeNames, end: next }
        }
        if (next === position) {
            return { attributeNames, end: -1 }
        }
        position = next
    }
}
