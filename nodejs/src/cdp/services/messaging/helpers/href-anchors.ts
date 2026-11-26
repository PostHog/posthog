import { OpeningTag, asciiLowerCase, readOpeningTag } from './opening-tag'

export type HrefAnchor = {
    html: string
    href: string
}

const COMMENT_START = /<!--(?!\[if\b[^<>]*\]>)/iy
const COMMENT_END = /(?<=--)>|--!>/g
const TAG_NAME = /<(\/?)([A-Za-z][^\t\n\f\r />]*)/y
const JAVASCRIPT_SCHEME = /^javascript:/i
const RAW_TEXT_ELEMENTS = ['script', 'style', 'textarea', 'title', 'xmp', 'iframe', 'noembed', 'noframes']
const FOREIGN_ELEMENTS = ['svg', 'math']
const CDATA_START = /<!\[CDATA\[/y
const DECLARATION_START = /<(?:[!?]|\/(?![A-Za-z]))/y

const rawTextEndFinder = (html: string): ((name: string, from: number) => number) => {
    const unclosed = new Set<string>()
    return (name, from) => {
        const endTag = new RegExp(`</${name}[\\t\\n\\f\\r />]`, 'gi')
        endTag.lastIndex = from
        const end = unclosed.has(name) ? -1 : (endTag.exec(html)?.index ?? -1)
        if (end === -1) {
            unclosed.add(name)
        }
        return end
    }
}

const trackableHref = (tag: OpeningTag): string | null =>
    tag.attributes.findLast(({ name, value }) => name === 'href' && value !== null && !JAVASCRIPT_SCHEME.test(value))
        ?.value ?? null

export const replaceHrefAnchors = (html: string, replace: (anchor: HrefAnchor) => string): string => {
    const pieces: string[] = []
    let copiedUpTo = 0
    let open: { start: number; href: string } | null = null
    let commentsCanClose = true
    let quotesCanClose = true
    let cdataCanClose = true
    let declarationsCanClose = true
    let foreignDepth = 0
    const rawTextEnd = rawTextEndFinder(html)

    for (let position = html.indexOf('<'); position !== -1; position = html.indexOf('<', position)) {
        COMMENT_START.lastIndex = position
        if (COMMENT_START.test(html)) {
            COMMENT_END.lastIndex = position + '<!--'.length
            commentsCanClose = commentsCanClose && COMMENT_END.test(html)
            position = commentsCanClose ? COMMENT_END.lastIndex : position + 1
            continue
        }
        CDATA_START.lastIndex = position
        if (foreignDepth > 0 && CDATA_START.test(html)) {
            const end: number = cdataCanClose ? html.indexOf(']]>', CDATA_START.lastIndex) : -1
            cdataCanClose = end !== -1
            position = cdataCanClose ? end + ']]>'.length : position + 1
            continue
        }
        DECLARATION_START.lastIndex = position
        if (DECLARATION_START.test(html)) {
            const end: number = declarationsCanClose ? html.indexOf('>', position) : -1
            declarationsCanClose = end !== -1
            position = declarationsCanClose ? end + 1 : position + 1
            continue
        }
        TAG_NAME.lastIndex = position
        const tagName = TAG_NAME.exec(html)
        if (!tagName) {
            position += 1
            continue
        }
        const name = asciiLowerCase(tagName[2])
        const isEndTag = tagName[1] === '/'
        const isAnchor = name === 'a'
        const attributesStart = TAG_NAME.lastIndex
        let tag = quotesCanClose ? readOpeningTag(html, attributesStart, isAnchor) : null
        if (!tag || tag.end === -1) {
            quotesCanClose = false
            const cut = html.indexOf('>', attributesStart)
            if (cut === -1) {
                break
            }
            const { attributes, selfClosing } = readOpeningTag(
                html.slice(position, cut + 1),
                attributesStart - position,
                isAnchor
            )
            tag = {
                selfClosing,
                attributes: attributes
                    .filter(({ end }) => end <= cut - position)
                    .map((attribute) => ({
                        ...attribute,
                        start: attribute.start + position,
                        end: attribute.end + position,
                    })),
                end: cut,
            }
        }
        if (FOREIGN_ELEMENTS.includes(name) && !tag.selfClosing) {
            foreignDepth = isEndTag ? Math.max(0, foreignDepth - 1) : foreignDepth + 1
        }
        if (!isEndTag && foreignDepth === 0 && RAW_TEXT_ELEMENTS.includes(name)) {
            const end = rawTextEnd(name, tag.end + 1)
            position = end === -1 ? tag.end + 1 : end
            continue
        }
        if (isAnchor && foreignDepth > 0 && tag.selfClosing) {
            position = tag.end + 1
            continue
        }
        if (isAnchor && open) {
            const end = isEndTag ? tag.end + 1 : position
            pieces.push(
                html.slice(copiedUpTo, open.start),
                replace({ html: html.slice(open.start, end), href: open.href })
            )
            copiedUpTo = end
            open = null
        }
        if (isAnchor && !isEndTag) {
            const href = trackableHref(tag)
            open = href === null ? null : { start: position, href }
        }
        position = tag.end + 1
    }
    if (open) {
        pieces.push(html.slice(copiedUpTo, open.start), replace({ html: html.slice(open.start), href: open.href }))
        copiedUpTo = html.length
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}
