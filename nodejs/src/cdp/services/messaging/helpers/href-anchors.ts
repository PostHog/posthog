import { DefaultTreeAdapterMap, parse, parseFragment } from 'parse5'

import { escapeHtml } from './escape-html'

export type AnchorAttribute = {
    // As a browser reads it, with character references decoded. Empty for an attribute written without `=`.
    value: string
}

export type HrefAnchor = {
    href: string
    // A browser keeps the first of two same-named attributes, so this returns the first.
    attribute: (name: string) => AnchorAttribute | undefined
}

// Sets the first attribute called `name`, or adds it when the tag has none. A `null` value writes the bare name.
export type AnchorEdit = {
    name: string
    value: string | null
}

type ScannedAttribute = {
    name: string
    rawName: string
    value: string
    hasValue: boolean
    quoted: boolean
    start: number
    // Where the value starts in the source, after any opening quote.
    valueStart: number
    end: number
}

type ScannedTag = {
    start: number
    // The attributes a browser keeps: the first of each name.
    attributes: ScannedAttribute[]
    // The last attribute written in the tag, a dropped repeat included.
    last: SourceAttribute | undefined
    // Where an added attribute goes: the `>`, or the `/` of a self-closing `/>`.
    insertAt: number
}

type Node = DefaultTreeAdapterMap['node']
type Element = DefaultTreeAdapterMap['element']

const JAVASCRIPT_SCHEME = /^javascript:/i

const isSpace = (char: string): boolean =>
    char === ' ' || char === '\t' || char === '\n' || char === '\f' || char === '\r'

// Email clients run no scripts, so `<noscript>` content is read as markup.
const PARSE_OPTIONS = { sourceCodeLocationInfo: true, scriptingEnabled: false } as const

// A same-length stand-in for `<!--` inside a comment, where it is text. `<_` opens no tag.
const COMMENT_OPENING = '<!--'
const COMMENT_OPENING_AS_TEXT = '<_--'

type SourceAttribute = Omit<ScannedAttribute, 'name' | 'value'>

// Splits a start tag into its attributes as the HTML tokenizer does, repeats included. `close` is the tag's `>`.
const readSourceAttributes = (html: string, tagStart: number, close: number): SourceAttribute[] => {
    const attributes: SourceAttribute[] = []
    let cursor = tagStart + 1
    while (cursor < close && !isSpace(html[cursor]) && html[cursor] !== '/') {
        cursor++
    }
    while (cursor < close) {
        if (isSpace(html[cursor]) || html[cursor] === '/') {
            cursor++
            continue
        }
        const start = cursor
        // A name may start with `=`; any later `=` starts its value.
        cursor++
        while (cursor < close && !isSpace(html[cursor]) && html[cursor] !== '/' && html[cursor] !== '=') {
            cursor++
        }
        const rawName = html.slice(start, cursor)
        let end = cursor
        while (cursor < close && isSpace(html[cursor])) {
            cursor++
        }
        const hasValue = cursor < close && html[cursor] === '='
        let quoted = false
        let valueStart = end
        if (hasValue) {
            cursor++
            while (cursor < close && isSpace(html[cursor])) {
                cursor++
            }
            const quote = html[cursor]
            quoted = cursor < close && (quote === '"' || quote === "'")
            valueStart = quoted ? cursor + 1 : cursor
            cursor = valueStart
            if (quoted) {
                // parse5 found the tag's `>` after this value, so the closing quote comes before it.
                const closingQuote = html.indexOf(quote, valueStart)
                cursor = closingQuote < 0 || closingQuote > close ? close : closingQuote + 1
            } else {
                while (cursor < close && !isSpace(html[cursor])) {
                    cursor++
                }
            }
            end = cursor
        }
        attributes.push({ rawName, hasValue, quoted, start, valueStart, end })
    }
    return attributes
}

// parse5 keeps the first attribute of each name and keys their locations by lowercased source name, so in source
// order the two lists pair up by index. Only where each one starts is taken from parse5, because a location
// ends at the name when no space follows the value.
const readAnchor = (html: string, base: number, element: Element, inComment: boolean): ScannedTag | null => {
    const location = element.sourceCodeLocation?.startTag
    // An anchor the parser reopens after a misnested end tag has no location: it is the same link again.
    if (!location) {
        return null
    }
    const start = base + location.startOffset
    const close = base + location.endOffset - 1
    const source = readSourceAttributes(html, start, close)
    const byStart = new Map(source.map((attribute) => [attribute.start, attribute]))
    const attributes: ScannedAttribute[] = []
    // Sorted, because an object lists integer-like keys such as `4` first.
    const locations = Object.entries(element.sourceCodeLocation?.attrs ?? {}).sort(
        ([, a], [, b]) => a.startOffset - b.startOffset
    )
    locations.forEach(([name, attributeLocation], index) => {
        const attribute = byStart.get(base + attributeLocation.startOffset)
        if (!attribute) {
            return
        }
        let value = element.attrs[index]?.value ?? ''
        if (inComment && html.slice(attribute.start, attribute.end).includes(COMMENT_OPENING)) {
            value = value.replaceAll(COMMENT_OPENING_AS_TEXT, COMMENT_OPENING)
        }
        attributes.push({ ...attribute, name, value })
    })
    const last = source[source.length - 1]
    const selfClosing = html[close - 1] === '/' && (!last || last.end < close)
    return { start, attributes, last, insertAt: selfClosing ? close - 1 : close }
}

// Collects the opening `<a>` tags a browser reads, in source order. Comment content is read as markup too, because
// Outlook renders the links inside its `<!--[if mso]>` blocks. That read takes a `<!--` as text, so each character
// is parsed at most twice however many comments a comment opens.
const scanAnchors = (html: string, root: Node, base: number, inComment: boolean, anchors: ScannedTag[]): void => {
    const pending: Node[] = [root]
    while (pending.length > 0) {
        const node = pending.pop()!
        if (node.nodeName === '#comment') {
            if (!inComment) {
                scanComment(html, node as DefaultTreeAdapterMap['commentNode'], anchors)
            }
            continue
        }
        if (node.nodeName === 'a') {
            const anchor = readAnchor(html, base, node as Element, inComment)
            if (anchor) {
                anchors.push(anchor)
            }
        }
        if ('childNodes' in node) {
            // A loop, not a spread: a spread passes every child as an argument, and a body can hold more than V8 takes.
            for (const child of node.childNodes) {
                pending.push(child)
            }
        }
        if (node.nodeName === 'template') {
            pending.push((node as DefaultTreeAdapterMap['template']).content)
        }
    }
}

const scanComment = (html: string, comment: DefaultTreeAdapterMap['commentNode'], anchors: ScannedTag[]): void => {
    const location = comment.sourceCodeLocation
    if (!location || !html.startsWith(COMMENT_OPENING, location.startOffset)) {
        return
    }
    const raw = html.slice(location.startOffset, location.endOffset)
    const contentStart = location.startOffset + COMMENT_OPENING.length
    const contentEnd = location.endOffset - (raw.endsWith('--!>') ? 4 : raw.endsWith('-->') ? 3 : 0)
    if (contentEnd <= contentStart) {
        return
    }
    const content = html.slice(contentStart, contentEnd).replaceAll(COMMENT_OPENING, COMMENT_OPENING_AS_TEXT)
    scanAnchors(html, parseFragment(content, PARSE_OPTIONS), contentStart, true, anchors)
}

type Scan = {
    anchors: ScannedTag[]
    // The `<` of the body end tag a browser reads last, or -1.
    bodyEnd: number
}

const scanHtml = (html: string): Scan => {
    const document = parse(html, PARSE_OPTIONS)
    const anchors: ScannedTag[] = []
    scanAnchors(html, document, 0, false, anchors)
    // Tree order is not source order: a link written inside a table moves before it.
    anchors.sort((a, b) => a.start - b.start)
    const root = document.childNodes.find((node): node is Element => node.nodeName === 'html')
    const body = root?.childNodes.find((node): node is Element => node.nodeName === 'body')
    return { anchors, bodyEnd: body?.sourceCodeLocation?.endTag?.startOffset ?? -1 }
}

const firstByName = (attributes: ScannedAttribute[]): Map<string, ScannedAttribute> => {
    const first = new Map<string, ScannedAttribute>()
    for (const attribute of attributes) {
        if (!first.has(attribute.name)) {
            first.set(attribute.name, attribute)
        }
    }
    return first
}

// Calls `edit` for each anchor with a usable href, in document order, and applies the edit it returns to the
// opening tag. `beforeBodyEnd` goes before the body end tag a browser reads, not a `</body>` inside an attribute, a
// comment or raw text; an email without one gets none. The rest of the email stays byte for byte as written.
export const editHrefAnchors = (
    html: string,
    edit: (anchor: HrefAnchor) => AnchorEdit | null,
    beforeBodyEnd?: string
): string => {
    const { anchors: tags, bodyEnd } = scanHtml(html)

    const pieces: string[] = []
    let copiedUpTo = 0
    // The body end tag sits outside every anchor tag, so it never splits an edit.
    let bodyEndPending = beforeBodyEnd !== undefined && bodyEnd >= 0
    const insertBodyEndMarkup = (): void => {
        pieces.push(html.slice(copiedUpTo, bodyEnd), beforeBodyEnd!)
        copiedUpTo = bodyEnd
        bodyEndPending = false
    }
    for (const tag of tags) {
        if (bodyEndPending && tag.start > bodyEnd) {
            insertBodyEndMarkup()
        }
        const attributes = firstByName(tag.attributes)
        const href = attributes.get('href')
        if (!href || !href.hasValue || (!href.quoted && href.value === '')) {
            continue
        }
        // Read on the source text, not the decoded value, so an encoded scheme still counts as a link, as it always has.
        if (JAVASCRIPT_SCHEME.test(html.slice(href.valueStart, href.valueStart + 'javascript:'.length))) {
            continue
        }
        const change = edit({ href: href.value, attribute: (name) => attributes.get(name) })
        if (!change) {
            continue
        }
        const existing = attributes.get(change.name)
        const name = existing?.rawName ?? change.name
        // `<` and `>` are escaped too: a raw `-->` would end an Outlook conditional comment around the link.
        const written = change.value === null ? name : `${name}="${escapeHtml(change.value)}"`

        if (existing) {
            pieces.push(html.slice(copiedUpTo, existing.start), written)
            copiedUpTo = existing.end
            continue
        }
        const last = tag.last
        if (last?.hasValue && !last.quoted && last.valueStart === last.end) {
            // `title=>` followed by ` name` would make `name` the value of `title`, so the empty value gets quotes.
            pieces.push(html.slice(copiedUpTo, last.start), `${last.rawName}="" ${written}`)
        } else {
            // A loop, not /\s+$/, which backtracks quadratically over a long run of spaces inside the tag.
            let before = tag.insertAt
            while (before > 0 && isSpace(html[before - 1])) {
                before--
            }
            pieces.push(html.slice(copiedUpTo, before), ` ${written}`)
        }
        // From the `/` of a self-closing `/>`, which closes an SVG link.
        copiedUpTo = tag.insertAt
    }
    if (bodyEndPending) {
        insertBodyEndMarkup()
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}
