import { HtmlAttribute, HtmlOpeningTag, findAttribute, scanOpeningTag } from './html-attributes'

export type HrefAnchor = {
    // The anchor from `<a` through `</a>`.
    html: string
    href: string
    // Positions in both are relative to `html`.
    hrefAttribute: HtmlAttribute
    openingTag: HtmlOpeningTag
}

type IndexFinder = (from: number) => number

const memoizedFinder = (html: string, pattern: RegExp): IndexFinder => {
    const search = new RegExp(pattern)
    let searchedFrom = -1
    let found = -1
    return (from) => {
        if (searchedFrom === -1 || from < searchedFrom || (found !== -1 && from > found)) {
            search.lastIndex = from
            found = search.exec(html)?.index ?? -1
            searchedFrom = from
        }
        return found
    }
}

const JAVASCRIPT_SCHEME = /^javascript:/i

const shiftAttribute = (attribute: HtmlAttribute, by: number): HtmlAttribute => ({
    ...attribute,
    start: attribute.start - by,
    end: attribute.end - by,
})

const shiftTag = (tag: HtmlOpeningTag, by: number): HtmlOpeningTag => ({
    attributes: tag.attributes.map((attribute) => shiftAttribute(attribute, by)),
    insertAt: tag.insertAt - by,
    end: tag.end - by,
})

export const replaceHrefAnchors = (html: string, replace: (anchor: HrefAnchor) => string): string => {
    const nextAnchorStart = memoizedFinder(html, /<a\b/gi)
    const nextAnchorClose = memoizedFinder(html, /<\/a>/gi)

    const pieces: string[] = []
    let copiedUpTo = 0
    let searchFrom = 0

    for (let start = nextAnchorStart(searchFrom); start !== -1; start = nextAnchorStart(searchFrom)) {
        const tag = scanOpeningTag(html, start + '<a'.length)
        if (!tag) {
            break
        }
        searchFrom = tag.end
        const attribute = findAttribute(tag, 'href')
        const href = attribute?.value
        if (!attribute || href == null || (href === '' && !attribute.quoted) || JAVASCRIPT_SCHEME.test(href)) {
            continue
        }
        const close = nextAnchorClose(tag.end)
        if (close === -1) {
            break
        }
        const end = close + '</a>'.length
        pieces.push(
            html.slice(copiedUpTo, start),
            replace({
                html: html.slice(start, end),
                href,
                hrefAttribute: shiftAttribute(attribute, start),
                openingTag: shiftTag(tag, start),
            })
        )
        copiedUpTo = searchFrom = end
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}
