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

const valueStream = (html: string, valueEnd: RegExp): ValueStream => ({
    nextValueEnd: memoizedFinder(html, valueEnd),
    nextTagEnd: memoizedFinder(html, />/g),
    nextAnchorClose: memoizedFinder(html, /<\/a>/gi),
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
        return anchorClose === -1 ? null : { href: value.href, end: anchorClose + '</a>'.length }
    }
}

const attribute =
    /([\t\n\f\r /]*)([^\t\n\f\r />][^\t\n\f\r />=]*)(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:"[^"]*"|'[^']*'|[^\t\n\f\r >]*))?/y

export const replaceHrefAnchors = (html: string, replace: (anchor: HrefAnchor) => string): string => {
    const nextAnchorStart = memoizedFinder(html, /<a(?=[\t\n\f\r />])/gi)
    const hrefMatchAt = hrefMatcher(html)
    const nextAttribute = (from: number): RegExpExecArray | null => {
        attribute.lastIndex = from
        return attribute.exec(html)
    }

    const pieces: string[] = []
    let copiedUpTo = 0
    let searchFrom = 0

    for (let start = nextAnchorStart(searchFrom); start !== -1; start = nextAnchorStart(searchFrom)) {
        let attributesEnd = start + '<a'.length
        let hrefRead = false
        let match: HrefValue | null = null
        for (let found = nextAttribute(attributesEnd); found && !match; found = nextAttribute(attributesEnd)) {
            attributesEnd = found.index + found[0].length
            if (!hrefRead && found[2].toLowerCase() === 'href') {
                hrefRead = true
                match = hrefMatchAt(found.index + found[1].length)
            }
        }
        if (!match) {
            searchFrom = attributesEnd
            continue
        }
        pieces.push(html.slice(copiedUpTo, start), replace({ html: html.slice(start, match.end), href: match.href }))
        copiedUpTo = searchFrom = match.end
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}
