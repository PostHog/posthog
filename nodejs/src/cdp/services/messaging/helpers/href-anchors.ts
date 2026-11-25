import { readOpeningTag } from './opening-tag'

export type HrefAnchor = {
    html: string
    href: string
}

type IndexFinder = (from: number) => number

type HrefValue = { href: string; end: number }

type ValueStream = {
    nextValueEnd: IndexFinder
    nextTagEnd: IndexFinder
    nextAnchorClose: IndexFinder
    nextCloseEnd: IndexFinder
}

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

const outsideComments = (html: string, pattern: RegExp): IndexFinder => {
    const nextMatch = memoizedFinder(html, pattern)
    const nextCommentStart = memoizedFinder(html, /<!--(?!\[if\b)/gi)
    const nextCommentEnd = memoizedFinder(html, /(?<=--!?)>/g)
    return (from) => {
        for (let position = from; ; ) {
            const match = nextMatch(position)
            const commentStart = nextCommentStart(position)
            if (match === -1 || commentStart === -1 || match < commentStart) {
                return match
            }
            const commentEnd = nextCommentEnd(commentStart + '<!'.length)
            if (commentEnd === -1) {
                return match
            }
            position = commentEnd + 1
        }
    }
}

const valueStream = (html: string, valueEnd: RegExp): ValueStream => ({
    nextValueEnd: memoizedFinder(html, valueEnd),
    nextTagEnd: memoizedFinder(html, />/g),
    nextAnchorClose: outsideComments(html, /<\/a[\t\n\f\r />]/gi),
    nextCloseEnd: memoizedFinder(html, />/g),
})

const hrefMatcher = (html: string): ((hrefStart: number) => HrefValue | null) => {
    const assignment = /\s*=\s*/y
    const javascriptScheme = /javascript:/iy
    const doubleQuoted = valueStream(html, /"/g)
    const singleQuoted = valueStream(html, /'/g)
    const unquoted = valueStream(html, /['">\s]/g)

    const isJavascriptAt = (position: number): boolean => {
        javascriptScheme.lastIndex = position
        return javascriptScheme.test(html)
    }

    const quotedValue = (valueStart: number, stream: ValueStream): HrefValue | null => {
        if (isJavascriptAt(valueStart + 1)) {
            return null
        }
        const closingQuote = stream.nextValueEnd(valueStart + 1)
        return closingQuote === -1 ? null : { href: html.slice(valueStart + 1, closingQuote), end: closingQuote + 1 }
    }

    const unquotedValue = (valueStart: number): HrefValue | null => {
        if (isJavascriptAt(valueStart)) {
            return null
        }
        const stop = unquoted.nextValueEnd(valueStart)
        const end = stop === -1 ? html.length : stop
        return end === valueStart ? null : { href: html.slice(valueStart, end), end }
    }

    return (hrefStart) => {
        assignment.lastIndex = hrefStart + 'href'.length
        if (!assignment.test(html)) {
            return null
        }
        const valueStart = assignment.lastIndex
        const quote = html[valueStart]
        const stream = quote === '"' ? doubleQuoted : quote === "'" ? singleQuoted : unquoted
        const value = stream === unquoted ? unquotedValue(valueStart) : quotedValue(valueStart, stream)
        if (!value) {
            return null
        }
        const tagEnd = stream.nextTagEnd(value.end)
        const anchorClose = tagEnd === -1 ? -1 : stream.nextAnchorClose(tagEnd + 1)
        const closeEnd = anchorClose === -1 ? -1 : stream.nextCloseEnd(anchorClose + '</a'.length)
        return closeEnd === -1 ? null : { href: value.href, end: closeEnd + 1 }
    }
}

export const replaceHrefAnchors = (html: string, replace: (anchor: HrefAnchor) => string): string => {
    const nextAnchorStart = outsideComments(html, /<a\b/gi)
    const nextHref = memoizedFinder(html, /\bhref/gi)
    const hrefMatchAt = hrefMatcher(html)

    const pieces: string[] = []
    let copiedUpTo = 0
    let searchFrom = 0
    let unscannedHrefsFrom = 0
    let lastMatch: { hrefStart: number; match: HrefValue } | null = null

    for (let start = nextAnchorStart(searchFrom); start !== -1; start = nextAnchorStart(searchFrom)) {
        const attributesStart = start + '<a'.length
        const tagEnd = readOpeningTag(html, attributesStart).end
        const lastHrefStart = tagEnd === -1 ? html.length : tagEnd
        const firstHrefStart = Math.max(unscannedHrefsFrom, attributesStart)
        for (let hrefStart = nextHref(firstHrefStart); hrefStart !== -1 && hrefStart <= lastHrefStart; ) {
            const match = hrefMatchAt(hrefStart)
            if (match) {
                lastMatch = { hrefStart, match }
            }
            hrefStart = nextHref(hrefStart + 1)
        }
        unscannedHrefsFrom = Math.max(unscannedHrefsFrom, lastHrefStart + 1)
        if (!lastMatch || lastMatch.hrefStart < attributesStart) {
            searchFrom = tagEnd === -1 ? html.length : tagEnd + 1
            continue
        }
        const { href, end } = lastMatch.match
        pieces.push(html.slice(copiedUpTo, start), replace({ html: html.slice(start, end), href }))
        copiedUpTo = searchFrom = end
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}
