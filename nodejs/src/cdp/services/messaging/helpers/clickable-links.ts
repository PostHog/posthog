import { Parser } from 'htmlparser2'

const HIDDEN_TAGS = new Set(['head', 'title', 'style', 'script', 'template'])

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

const EMPTY_BOGUS_COMMENT = /<!>/g
const COMMENT_END_AFTER_BANG = /--!>/g

const withCommentsBrowsersClose = (html: string): string =>
    html.replace(EMPTY_BOGUS_COMMENT, '<!---->').replace(COMMENT_END_AFTER_BANG, '-->')

export const clickableHrefs = (html: string): string[] => {
    const hrefs: string[] = []
    let hiddenDepth = 0
    const parser = new Parser(
        {
            onopentag(name, attributes) {
                if (HIDDEN_TAGS.has(name)) {
                    hiddenDepth++
                } else if (hiddenDepth === 0 && name === 'a' && attributes.href !== undefined) {
                    hrefs.push(trimUrlWhitespace(attributes.href))
                }
            },
            onclosetag(name) {
                if (HIDDEN_TAGS.has(name) && hiddenDepth > 0) {
                    hiddenDepth--
                }
            },
        },
        { decodeEntities: true, lowerCaseTags: true, lowerCaseAttributeNames: true, recognizeSelfClosing: true }
    )
    parser.write(withCommentsBrowsersClose(html))
    parser.end()
    return hrefs
}
