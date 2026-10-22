const WORD = /[\p{L}\p{N}_]+/gu

export type RankKey = number[]

const MIN_ALIAS_QUERY_LENGTH = 3
const STARTS_WITH = 1

export const searchWords = (text: string): string[] => text.toLowerCase().match(WORD) ?? []

export const FILTER_TOKEN = /(^|\s)([-!]\S+|(path|name|user|author|type|ref):("[^"]*"|\S*))/gi

export const freeWords = (query: string): string[] => searchWords(query.replace(FILTER_TOKEN, ' '))

function osaDistance(a: string, b: string): number {
    if (!a.length) {
        return b.length
    }
    if (!b.length) {
        return a.length
    }
    let previousPrevious: number[] = []
    let previous = Array.from({ length: b.length + 1 }, (_, j) => j)
    for (let i = 1; i <= a.length; i++) {
        const current = [i]
        for (let j = 1; j <= b.length; j++) {
            let value = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
            if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
                value = Math.min(value, previousPrevious[j - 2] + 1)
            }
            current.push(value)
        }
        previousPrevious = previous
        previous = current
    }
    return previous[b.length]
}

const singular = (word: string): string =>
    word.length > 3 && word.endsWith('s') && !word.endsWith('ss') ? word.slice(0, -1) : word

const singularText = (text: string): string => searchWords(text).map(singular).join(' ')

const allowedTypos = (token: string): number => (token.length < 5 ? 0 : token.length < 9 ? 1 : 2)

export function tokenTypos(token: string, word: string): number | null {
    if (word.startsWith(token) || word === singular(token)) {
        return 0
    }
    const budget = allowedTypos(token)
    if (!budget) {
        return null
    }
    const distance = Math.min(
        osaDistance(token, word.slice(0, token.length)),
        osaDistance(token, word),
        osaDistance(token, singular(word))
    )
    return distance <= budget ? distance : null
}

function bestMatch(token: string, words: string[]): [number, number] | null {
    let best: [number, number] | null = null
    for (let position = 0; position < words.length; position++) {
        const typos = tokenTypos(token, words[position])
        if (typos !== null && (!best || typos < best[0])) {
            best = [typos, position]
            if (typos === 0) {
                break
            }
        }
    }
    return best
}

const escapeRegExp = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function exactness(query: string, name: string, nameWords: string[]): number {
    if (name === query || singularText(name) === singularText(query)) {
        return 0
    }
    if (name.startsWith(query)) {
        return 1
    }
    if (nameWords.some((word) => word.startsWith(query)) || new RegExp(`(^|\\W)${escapeRegExp(query)}`).test(name)) {
        return 2
    }
    if (name.includes(query)) {
        return 3
    }
    if (
        nameWords
            .map((word) => word[0])
            .join('')
            .startsWith(query.replace(/ /g, ''))
    ) {
        return 4
    }
    return 5
}

function rankName(query: string, tokens: string[], name: string): RankKey | null {
    const lowerName = name.toLowerCase()
    const nameWords = searchWords(lowerName)
    let matched = 0
    let typos = 0
    let exactWords = 0
    const positions: number[] = []
    for (const token of tokens) {
        const hit = bestMatch(token, nameWords)
        if (!hit) {
            continue
        }
        matched++
        typos += hit[0]
        positions.push(hit[1])
        if (tokens.length > 1 && nameWords.some((word) => singular(word) === singular(token))) {
            exactWords++
        }
    }
    if (!matched) {
        return null
    }
    if (tokens.length === 1 && singularText(lowerName) === singularText(query)) {
        exactWords = 1
    }
    let proximity = 0
    for (let i = 1; i < positions.length; i++) {
        proximity +=
            Math.max(Math.abs(positions[i] - positions[i - 1]) - 1, 0) + (positions[i] < positions[i - 1] ? 1 : 0)
    }
    return [
        -matched,
        typos,
        proximity,
        matched === tokens.length ? 0 : 1,
        -exactWords,
        0,
        Math.min(exactness(query, lowerName, nameWords), STARTS_WITH),
        0,
        -Number.MAX_SAFE_INTEGER,
    ]
}

export const compareRanks = (a: RankKey, b: RankKey): number => {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
        if (a[i] !== b[i]) {
            return a[i] - b[i]
        }
    }
    return a.length - b.length
}

interface LocalRank {
    rank: RankKey
    matchedAlias: string | null
}

export function rankLocalItem(query: string, name: string, aliases: string[] = []): LocalRank | null {
    const normalized = query.trim().toLowerCase().replace(/\s+/g, ' ')
    const tokens = searchWords(normalized)
    if (!tokens.length) {
        return null
    }
    let best: LocalRank | null = null
    const byName = rankName(normalized, tokens, name)
    if (byName) {
        best = { rank: byName, matchedAlias: null }
    }
    for (const alias of normalized.length >= MIN_ALIAS_QUERY_LENGTH ? aliases : []) {
        const byAlias = rankName(normalized, tokens, alias)
        if (byAlias && (!best || compareRanks(byAlias, best.rank) < 0)) {
            best = { rank: byAlias, matchedAlias: alias }
        }
    }
    return best
}

interface HighlightSegment {
    text: string
    match: boolean
}

export function highlightSegments(name: string, words: string[]): HighlightSegment[] {
    if (!words.length) {
        return [{ text: name, match: false }]
    }
    const segments: HighlightSegment[] = []
    let cursor = 0
    for (const found of name.matchAll(WORD)) {
        const word = found[0].toLowerCase()
        const start = found.index ?? 0
        const prefix = words.find((token) => word.startsWith(token))
        const length = prefix
            ? prefix.length
            : words.some((token) => tokenTypos(token, word) !== null)
              ? word.length
              : 0
        if (!length) {
            continue
        }
        if (start > cursor) {
            segments.push({ text: name.slice(cursor, start), match: false })
        }
        segments.push({ text: name.slice(start, start + length), match: true })
        cursor = start + length
    }
    if (cursor < name.length) {
        segments.push({ text: name.slice(cursor), match: false })
    }
    return segments
}

export function strictLocalMatches<T extends { name: string; displayName?: string; searchKeywords?: string[] }>(
    items: T[],
    query: string
): T[] {
    const words = searchWords(query).length
    return items
        .map((item) => ({
            item,
            ranked: rankLocalItem(query, String(item.displayName || item.name), item.searchKeywords),
        }))
        .filter(({ ranked }) => ranked !== null && -ranked.rank[0] === words && ranked.rank[1] === 0)
        .sort((a, b) => compareRanks(a.ranked!.rank, b.ranked!.rank))
        .map(({ item }) => item)
}
