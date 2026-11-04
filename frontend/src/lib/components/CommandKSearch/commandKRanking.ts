const WORD = /[\p{L}\p{N}_]+/gu

export type RankKey = number[]

const MIN_ALIAS_QUERY_LENGTH = 3
const MAX_LOCAL_QUERY_LENGTH = 200
const STARTS_WITH = 1

export const searchWords = (text: string): string[] => text.toLowerCase().match(WORD) ?? []

const FILTER_KEY = '(?:path|name|user|author|type|ref)'

export const FILTER_TOKEN = new RegExp(`(^|\\s)([-!](?:${FILTER_KEY}:"[^"]*"|\\S+)|${FILTER_KEY}:("[^"]*"|\\S*))`, 'gi')

export const freeWords = (query: string): string[] => searchWords(query.replace(FILTER_TOKEN, ' '))

// Stops once every path is longer than limit, because a row's smallest value never shrinks.
function osaDistance(a: string, b: string, limit = Infinity): number {
    if (Math.abs(a.length - b.length) > limit) {
        return limit + 1
    }
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
        if (Math.min(...current) > limit) {
            return limit + 1
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
        osaDistance(token, word.slice(0, token.length), budget),
        osaDistance(token, word, budget),
        osaDistance(token, singular(word), budget)
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

function rankName(query: string, tokens: string[], name: string, indirect: number): RankKey | null {
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
        Math.min(...positions),
        Math.min(exactness(query, lowerName, nameWords), STARTS_WITH),
        indirect,
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

export function rankLocalItem(
    query: string,
    name: string,
    aliases: string[] = [],
    isTab = false,
    shortQueryAliases = false
): LocalRank | null {
    const normalized = query.trim().toLowerCase().replace(/\s+/g, ' ').slice(0, MAX_LOCAL_QUERY_LENGTH)
    const tokens = searchWords(normalized)
    if (!tokens.length) {
        return null
    }
    let best: LocalRank | null = null
    const byName = rankName(normalized, tokens, name, isTab ? 1 : 0)
    if (byName) {
        best = { rank: byName, matchedAlias: null }
    }
    for (const alias of shortQueryAliases || normalized.length >= MIN_ALIAS_QUERY_LENGTH ? aliases : []) {
        const byAlias = rankName(normalized, tokens, alias, isTab ? 2 : 1)
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

const UNIFIED_WORD = /[\p{L}\p{N}]+/gu

const unifiedWords = (text: string): string[] => text.toLowerCase().match(UNIFIED_WORD) ?? []

const unifiedSingularText = (text: string): string => unifiedWords(text).map(singular).join(' ')

export const SERVER_FRECENCY_INDEX = 7
export const SERVER_CREATED_INDEX = 8

export interface RankCandidate {
    name: string
    aliases?: string[]
    identity?: string[]
    context?: string[]
    frecency?: number
    createdAt?: number
    typePrior?: number
    indirect?: boolean
    matchesQuery?: boolean
    tierBoost?: number
}

interface CandidateRank {
    rank: RankKey
    matchedAlias: string | null
}

const MatchTier = {
    Exact: 0,
    ExactSingular: 1,
    ExactAlias: 2,
    Prefix: 3,
    PrefixSingular: 4,
    NameWords: 5,
    AliasWords: 6,
    Identity: 7,
    Partial: 8,
    Weak: 9,
} as const

type MatchTier = (typeof MatchTier)[keyof typeof MatchTier]

type Field = 'name' | 'alias' | 'identity' | 'context'

interface TokenHit {
    typos: number
    position: number
    field: Field
    wordStart: boolean
    alias?: string
}

const MAX_POSITION_PENALTY = 3
const MIN_PARTIAL_TOKEN_LENGTH = 3

export const isIdentityQuery = (query: string): boolean => /^\S*[.@]\S+$/.test(query.trim())

function hitInWords(token: string, words: string[]): Omit<TokenHit, 'field'> | null {
    let best: Omit<TokenHit, 'field'> | null = null
    for (let position = 0; position < words.length; position++) {
        const typos = tokenTypos(token, words[position])
        if (typos === 0) {
            return { typos, position, wordStart: true }
        }
        if (typos !== null && (!best || typos < best.typos)) {
            best = { typos, position, wordStart: true }
        }
    }
    // A literal match inside a word needs no typo, so it beats a fuzzy word match.
    const inside = token.length < MIN_PARTIAL_TOKEN_LENGTH ? -1 : words.findIndex((word) => word.includes(token))
    return inside >= 0 ? { typos: 0, position: inside, wordStart: false } : best
}

const isClean = (hit: Omit<TokenHit, 'field'> | null): boolean => !!hit && hit.typos === 0 && hit.wordStart

function cleanHit(token: string, candidate: RankCandidate, name: Omit<TokenHit, 'field'> | null): TokenHit | null {
    if (name && isClean(name)) {
        return { ...name, field: 'name' }
    }
    for (const alias of candidate.aliases ?? []) {
        const hit = hitInWords(token, unifiedWords(alias))
        if (hit && isClean(hit)) {
            return { ...hit, position: MAX_POSITION_PENALTY, field: 'alias', alias }
        }
    }
    const inIdentity = (candidate.identity ?? []).some((value) => value.toLowerCase().includes(token))
    return inIdentity ? { typos: 0, position: MAX_POSITION_PENALTY, field: 'identity', wordStart: true } : null
}

function tokenHit(token: string, candidate: RankCandidate, nameWords: string[]): TokenHit | null {
    const name = hitInWords(token, nameWords)
    const clean = cleanHit(token, candidate, name)
    if (clean) {
        return clean
    }
    const context = hitInWords(token, (candidate.context ?? []).flatMap(unifiedWords))
    const hits: TokenHit[] = [
        ...(name ? [{ ...name, field: 'name' as const }] : []),
        ...(candidate.aliases ?? []).flatMap((alias) => {
            const hit = hitInWords(token, unifiedWords(alias))
            return hit ? [{ ...hit, position: MAX_POSITION_PENALTY, field: 'alias' as const, alias }] : []
        }),
        ...(context ? [{ ...context, position: MAX_POSITION_PENALTY, field: 'context' as const }] : []),
        // The source already matched the whole search on fields the browser cannot see.
        ...(candidate.matchesQuery
            ? [{ typos: 0, position: MAX_POSITION_PENALTY, field: 'identity' as const, wordStart: true }]
            : []),
    ]
    return hits.length ? hits.reduce((best, hit) => (hit.typos < best.typos ? hit : best)) : null
}

function wholeQueryTier(query: string, candidate: RankCandidate): MatchTier | null {
    const exactQuery = unifiedWords(query).join(' ')
    const exactName = unifiedWords(candidate.name).join(' ')
    const singularQuery = unifiedSingularText(query)
    const singularName = unifiedSingularText(candidate.name)
    const rawQuery = query.trim().toLowerCase()
    const identity = isIdentityQuery(query) ? (candidate.identity ?? []).map((value) => value.toLowerCase()) : []
    const tiers: [MatchTier, () => boolean][] = [
        [MatchTier.Exact, () => exactName === exactQuery || identity.includes(rawQuery)],
        [MatchTier.ExactSingular, () => singularName === singularQuery],
        [
            MatchTier.ExactAlias,
            () => (candidate.aliases ?? []).some((alias) => unifiedSingularText(alias) === singularQuery),
        ],
        [
            MatchTier.Prefix,
            () => exactName.startsWith(exactQuery) || identity.some((value) => value.startsWith(rawQuery)),
        ],
        [MatchTier.PrefixSingular, () => singularName.startsWith(singularQuery)],
    ]
    return tiers.find(([, matches]) => matches())?.[0] ?? null
}

const WORD_TIERS: [MatchTier, (hits: TokenHit[]) => boolean][] = [
    [MatchTier.NameWords, (hits) => hits.every((hit) => hit.field === 'name' && isClean(hit))],
    [
        MatchTier.AliasWords,
        (hits) => hits.every((hit) => (hit.field === 'name' || hit.field === 'alias') && isClean(hit)),
    ],
    [
        MatchTier.Identity,
        (hits) => hits.some((hit) => hit.field === 'identity') && hits.every((hit) => hit.field !== 'context'),
    ],
    [MatchTier.Partial, (hits) => hits.every((hit) => hit.field === 'name')],
]

function matchTier(query: string, hits: (TokenHit | null)[], candidate: RankCandidate): MatchTier {
    const whole = wholeQueryTier(query, candidate)
    if (whole !== null) {
        return whole
    }
    if (hits.some((hit) => hit === null)) {
        return MatchTier.Weak
    }
    return WORD_TIERS.find(([, matches]) => matches(hits as TokenHit[]))?.[0] ?? MatchTier.Weak
}

function proximityOf(positions: number[]): number {
    let proximity = 0
    for (let i = 1; i < positions.length; i++) {
        proximity +=
            Math.max(Math.abs(positions[i] - positions[i - 1]) - 1, 0) + (positions[i] < positions[i - 1] ? 1 : 0)
    }
    return Math.min(proximity, MAX_POSITION_PENALTY)
}

const usageTier = (frecency: number): number => (frecency >= 1 ? 0 : frecency > 0 ? 1 : 2)

export function rankCandidate(query: string, candidate: RankCandidate): CandidateRank | null {
    const normalizedQuery = query.trim().toLowerCase().replace(/\s+/g, ' ').slice(0, MAX_LOCAL_QUERY_LENGTH)
    const tokens = [...new Set(unifiedWords(normalizedQuery))]
    if (!tokens.length) {
        return null
    }
    const nameWords = unifiedWords(candidate.name)
    const hits = tokens.map((token) => tokenHit(token, candidate, nameWords))
    const found = hits.filter((hit): hit is TokenHit => hit !== null)
    if (!found.length) {
        return null
    }
    const positions = found.filter((hit) => hit.field === 'name').map((hit) => hit.position)
    const frecency = candidate.frecency ?? 0
    return {
        rank: [
            -found.length,
            found.reduce((sum, hit) => sum + hit.typos, 0),
            Math.max(matchTier(normalizedQuery, hits, candidate) - (candidate.tierBoost ?? 0), 0),
            usageTier(frecency),
            proximityOf(positions),
            Math.min(...positions, MAX_POSITION_PENALTY),
            candidate.typePrior ?? 1,
            Number(!!candidate.indirect),
            -Math.round(frecency * 1000),
            -(candidate.createdAt ?? 0),
        ],
        matchedAlias: found.find((hit) => hit.field === 'alias')?.alias ?? null,
    }
}
