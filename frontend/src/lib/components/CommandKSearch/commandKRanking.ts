import { PICKED_THRESHOLD } from './commandKPickMemory'

const WORD = /[\p{L}\p{N}_]+/gu

export type RankKey = number[]

const MIN_ALIAS_QUERY_LENGTH = 3
const MAX_LOCAL_QUERY_LENGTH = 200
const STARTS_WITH = 1

export const searchWords = (text: string): string[] => text.toLowerCase().match(WORD) ?? []

const FILTER_KEY = '(?:path|name|user|author|type|ref)'

export const FILTER_TOKEN = new RegExp(`(^|\\s)([-!](?:${FILTER_KEY}:"[^"]*"|\\S+)|${FILTER_KEY}:("[^"]*"|\\S*))`, 'gi')

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

export function rankLocalItem(query: string, name: string, aliases: string[] = [], isTab = false): LocalRank | null {
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
    for (const alias of normalized.length >= MIN_ALIAS_QUERY_LENGTH ? aliases : []) {
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
    picked?: number
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
    if (best || token.length < MIN_PARTIAL_TOKEN_LENGTH) {
        return best
    }
    const position = words.findIndex((word) => word.includes(token))
    return position >= 0 ? { typos: 0, position, wordStart: false } : null
}

function tokenHit(token: string, candidate: RankCandidate, nameWords: string[]): TokenHit | null {
    const name = hitInWords(token, nameWords)
    if (name && name.typos === 0 && name.wordStart) {
        return { ...name, field: 'name' }
    }
    for (const alias of candidate.aliases ?? []) {
        const hit = hitInWords(token, searchWords(alias))
        if (hit && hit.typos === 0 && hit.wordStart) {
            return { ...hit, position: MAX_POSITION_PENALTY, field: 'alias', alias }
        }
    }
    if ((candidate.identity ?? []).some((value) => value.toLowerCase().includes(token))) {
        return { typos: 0, position: MAX_POSITION_PENALTY, field: 'identity', wordStart: true }
    }
    if (name) {
        return { ...name, field: 'name' }
    }
    const context = hitInWords(token, (candidate.context ?? []).flatMap(searchWords))
    if (context) {
        return { ...context, position: MAX_POSITION_PENALTY, field: 'context' }
    }
    return candidate.matchesQuery
        ? { typos: 0, position: MAX_POSITION_PENALTY, field: 'identity', wordStart: true }
        : null
}

function matchTier(query: string, hits: (TokenHit | null)[], candidate: RankCandidate): MatchTier {
    const exactQuery = searchWords(query).join(' ')
    const exactName = searchWords(candidate.name).join(' ')
    const singularQuery = singularText(query)
    const singularName = singularText(candidate.name)
    const identityQuery = isIdentityQuery(query)
    const rawQuery = query.trim().toLowerCase()
    const identity = (candidate.identity ?? []).map((value) => value.toLowerCase())
    if (exactName === exactQuery || (identityQuery && identity.includes(rawQuery))) {
        return MatchTier.Exact
    }
    if (singularName === singularQuery) {
        return MatchTier.ExactSingular
    }
    if ((candidate.aliases ?? []).some((alias) => singularText(alias) === singularQuery)) {
        return MatchTier.ExactAlias
    }
    if (exactName.startsWith(exactQuery) || (identityQuery && identity.some((value) => value.startsWith(rawQuery)))) {
        return MatchTier.Prefix
    }
    if (singularName.startsWith(singularQuery)) {
        return MatchTier.PrefixSingular
    }
    if (!hits.every((hit) => hit !== null)) {
        return MatchTier.Weak
    }
    const found = hits as TokenHit[]
    const clean = (hit: TokenHit): boolean => hit.wordStart && hit.typos === 0
    if (found.every((hit) => hit.field === 'name' && clean(hit))) {
        return MatchTier.NameWords
    }
    if (found.every((hit) => (hit.field === 'name' || hit.field === 'alias') && clean(hit))) {
        return MatchTier.AliasWords
    }
    if (found.some((hit) => hit.field === 'identity') && found.every((hit) => hit.field !== 'context')) {
        return MatchTier.Identity
    }
    return found.every((hit) => hit.field === 'name') ? MatchTier.Partial : MatchTier.Weak
}

const usageTier = (frecency: number): number => (frecency >= 1 ? 0 : frecency > 0 ? 1 : 2)

export function rankCandidate(query: string, candidate: RankCandidate): CandidateRank | null {
    const normalizedQuery = query.trim().toLowerCase().replace(/\s+/g, ' ').slice(0, MAX_LOCAL_QUERY_LENGTH)
    const tokens = [...new Set(searchWords(normalizedQuery))]
    if (!tokens.length) {
        return null
    }
    const nameWords = searchWords(candidate.name)
    const hits = tokens.map((token) => tokenHit(token, candidate, nameWords))
    const found = hits.filter((hit): hit is TokenHit => hit !== null)
    if (!found.length) {
        return null
    }
    const positions = found.filter((hit) => hit.field === 'name').map((hit) => hit.position)
    let proximity = 0
    for (let i = 1; i < positions.length; i++) {
        proximity +=
            Math.max(Math.abs(positions[i] - positions[i - 1]) - 1, 0) + (positions[i] < positions[i - 1] ? 1 : 0)
    }
    const frecency = candidate.frecency ?? 0
    return {
        rank: [
            -found.length,
            found.reduce((sum, hit) => sum + hit.typos, 0),
            Number((candidate.picked ?? 0) < PICKED_THRESHOLD),
            Math.max(matchTier(normalizedQuery, hits, candidate) - (candidate.tierBoost ?? 0), 0),
            usageTier(frecency),
            Math.min(proximity, MAX_POSITION_PENALTY),
            Math.min(...positions, MAX_POSITION_PENALTY),
            candidate.typePrior ?? 1,
            Number(!!candidate.indirect),
            -Math.round(frecency * 1000),
            -(candidate.createdAt ?? 0),
        ],
        matchedAlias: found.find((hit) => hit.field === 'alias')?.alias ?? null,
    }
}
