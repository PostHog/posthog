export type HtmlAttribute = {
    // Lowercased, as an HTML parser compares attribute names.
    name: string
    // `null` for an attribute written without `=`.
    value: string | null
    quoted: boolean
    // The span of the whole attribute, name through closing quote.
    start: number
    end: number
}

export type HtmlOpeningTag = {
    attributes: HtmlAttribute[]
    // Where an appended attribute goes: before the `>`, or before the `/` of a self-closing `/>`.
    insertAt: number
    // Just past the `>` that ends the tag.
    end: number
}

const isSpace = (char: string): boolean =>
    char === ' ' || char === '\t' || char === '\n' || char === '\f' || char === '\r'

// Reads the attributes of an opening tag the way the HTML tokenizer does, from just after the tag name, so a `>`
// or a quote inside a quoted value never ends the tag. Returns null when the document ends inside the tag, since
// a browser then drops the tag and everything after it.
export const scanOpeningTag = (html: string, from: number): HtmlOpeningTag | null => {
    const attributes: HtmlAttribute[] = []
    let position = from
    while (position < html.length) {
        const char = html[position]
        if (isSpace(char)) {
            position++
            continue
        }
        if (char === '>') {
            return { attributes, insertAt: position, end: position + 1 }
        }
        if (char === '/') {
            if (html[position + 1] === '>') {
                return { attributes, insertAt: position, end: position + 2 }
            }
            position++
            continue
        }

        const start = position
        position++
        while (position < html.length && !isSpace(html[position]) && !'/>='.includes(html[position])) {
            position++
        }
        const name = html.slice(start, position).toLowerCase()

        let afterName = position
        while (afterName < html.length && isSpace(html[afterName])) {
            afterName++
        }
        if (html[afterName] !== '=') {
            attributes.push({ name, value: null, quoted: false, start, end: position })
            continue
        }

        position = afterName + 1
        while (position < html.length && isSpace(html[position])) {
            position++
        }
        const quote = html[position]
        if (quote === '"' || quote === "'") {
            const closing = html.indexOf(quote, position + 1)
            if (closing === -1) {
                return null
            }
            attributes.push({ name, value: html.slice(position + 1, closing), quoted: true, start, end: closing + 1 })
            position = closing + 1
            continue
        }
        const valueStart = position
        while (position < html.length && !isSpace(html[position]) && html[position] !== '>') {
            position++
        }
        attributes.push({ name, value: html.slice(valueStart, position), quoted: false, start, end: position })
    }
    return null
}

// A browser keeps the first of two same-named attributes and drops the rest.
export const findAttribute = (tag: HtmlOpeningTag, name: string): HtmlAttribute | undefined =>
    tag.attributes.find((attribute) => attribute.name === name)

export const withAttribute = (html: string, tag: HtmlOpeningTag, attribute: string): string => {
    // A loop, not /\s+$/, which backtracks quadratically over a long run of spaces inside the tag.
    let before = tag.insertAt
    while (before > 0 && isSpace(html[before - 1])) {
        before--
    }
    return `${html.slice(0, before)} ${attribute}>${html.slice(tag.end)}`
}
