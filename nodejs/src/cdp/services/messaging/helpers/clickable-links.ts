import { DefaultTreeAdapterMap, html, parse } from 'parse5'

const HIDDEN_ELEMENTS = new Set(['head', 'title', 'style', 'script', 'template', 'noscript', 'noframes'])

const isStrippedByUrlParser = (char: string): boolean => char <= ' '

export const trimUrlWhitespace = (href: string): string => {
    let start = 0
    let end = href.length
    while (start < end && isStrippedByUrlParser(href[start])) {
        start++
    }
    while (end > start && isStrippedByUrlParser(href[end - 1])) {
        end--
    }
    return href.slice(start, end)
}

const TEXT_LINK_START = /[hH][tT][tT][pP][sS]?:\/\/|[wW]{3}\./
const TEXT_LINK_END_PUNCTUATION = '.,;:!?\'")]}>*'
const LIQUID_TAG_START = /\{[{%]/

const withoutLinkEnd = (rest: string, { liquid }: { liquid: boolean }): string => {
    const tag = liquid ? rest.search(LIQUID_TAG_START) : -1
    let end = tag === -1 ? rest.length : tag
    while (end > 0 && TEXT_LINK_END_PUNCTUATION.includes(rest[end - 1])) {
        end--
    }
    return rest.slice(0, end)
}

export const textLinksTo = (text: string, base: string, { liquid }: { liquid: boolean }): string[] =>
    text.split(/\s+/).flatMap((word) => {
        const start = word.search(TEXT_LINK_START)
        const link = start === -1 ? '' : word.slice(start)
        return link.startsWith(base) ? [withoutLinkEnd(link.slice(base.length), { liquid })] : []
    })

type ParentNode = DefaultTreeAdapterMap['parentNode']

export const clickableHrefs = (body: string): string[] => {
    const hrefs: string[] = []
    const parents: ParentNode[] = [parse(body)]
    for (let parent = parents.pop(); parent; parent = parents.pop()) {
        for (const child of parent.childNodes) {
            if (!('tagName' in child) || HIDDEN_ELEMENTS.has(child.tagName)) {
                continue
            }
            const href =
                child.tagName === 'a' && child.namespaceURI === html.NS.HTML
                    ? child.attrs.find(({ name, prefix }) => name === 'href' && !prefix)
                    : undefined
            if (href) {
                hrefs.push(trimUrlWhitespace(href.value))
            }
            parents.push(child)
        }
    }
    return hrefs
}
