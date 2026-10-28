export function wildcardPatternMatchesPathname(pattern: string, pathname: string): boolean {
    const decodedPattern = decodeUnreserved(pattern)
    const endAnchored = decodedPattern.endsWith('$')
    const matchPattern = endAnchored ? decodedPattern.slice(0, -1) : decodedPattern
    const decodedPathname = decodeUnreserved(pathname)

    if (!matchPattern.includes('*')) {
        return endAnchored ? decodedPathname === matchPattern : decodedPathname.startsWith(matchPattern)
    }

    const literalSegments = matchPattern.split('*').filter(Boolean)
    if (literalSegments.length === 0) {
        return true
    }

    let nextSearchIndex = 0
    let nextSegmentIndex = 0
    if (!matchPattern.startsWith('*')) {
        const firstSegment = literalSegments[0]
        if (!decodedPathname.startsWith(firstSegment)) {
            return false
        }
        nextSearchIndex = firstSegment.length
        nextSegmentIndex = 1
    }

    let segmentSearchEnd = literalSegments.length
    let pathnameSearchEnd = decodedPathname.length
    if (endAnchored && !matchPattern.endsWith('*')) {
        const finalSegmentIndex = literalSegments.length - 1
        const finalSegment = literalSegments[finalSegmentIndex]
        if (!decodedPathname.endsWith(finalSegment)) {
            return false
        }
        segmentSearchEnd = finalSegmentIndex
        pathnameSearchEnd = decodedPathname.length - finalSegment.length
    }

    for (; nextSegmentIndex < segmentSearchEnd; nextSegmentIndex++) {
        const segment = literalSegments[nextSegmentIndex]
        const matchIndex = findLiteralSegment(decodedPathname, segment, nextSearchIndex, pathnameSearchEnd)
        if (matchIndex === -1) {
            return false
        }
        nextSearchIndex = matchIndex + segment.length
    }

    return nextSearchIndex <= pathnameSearchEnd
}

function findLiteralSegment(value: string, segment: string, startIndex: number, endIndex: number): number {
    const prefixLengths = buildPrefixLengths(segment)
    for (let index = startIndex, matchedLength = 0; index < endIndex; index++) {
        while (matchedLength > 0 && value[index] !== segment[matchedLength]) {
            matchedLength = prefixLengths[matchedLength - 1]
        }
        if (value[index] === segment[matchedLength]) {
            matchedLength++
        }
        if (matchedLength === segment.length) {
            return index - segment.length + 1
        }
    }
    return -1
}

function buildPrefixLengths(value: string): number[] {
    const prefixLengths = Array<number>(value.length).fill(0)
    for (let index = 1, matchedLength = 0; index < value.length; index++) {
        while (matchedLength > 0 && value[index] !== value[matchedLength]) {
            matchedLength = prefixLengths[matchedLength - 1]
        }
        if (value[index] === value[matchedLength]) {
            matchedLength++
        }
        prefixLengths[index] = matchedLength
    }
    return prefixLengths
}

function decodeUnreserved(value: string): string {
    return value.replace(/%[0-9A-Fa-f]{2}/g, (encoded) => {
        const character = String.fromCharCode(Number.parseInt(encoded.slice(1), 16))
        return /^[A-Za-z0-9._~-]$/.test(character) ? character : encoded.toUpperCase()
    })
}
