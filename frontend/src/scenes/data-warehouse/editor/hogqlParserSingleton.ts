import type { HogQLParser } from '@posthog/hogql-parser'

let parserPromise: Promise<HogQLParser> | null = null

function getParser(): Promise<HogQLParser> {
    if (!parserPromise) {
        parserPromise = import('@posthog/hogql-parser')
            .then((mod) => mod.default())
            .catch((error) => {
                // Reset so next call retries initialization
                parserPromise = null
                throw error
            })
    }
    return parserPromise
}

// `parseSelect` is a synchronous WASM call over the whole query, so it blocks the main thread for
// roughly 36ms per 1000 characters — seconds on a long query. Two callers make that far worse than
// once per edit: the SQL editor re-parses on every cursor move even though the text has not
// changed, and its decoration and table/column pipelines parse the same text one debounce apart,
// so the second request arrives while the first parse is still running.
//
// Memoizing the last few results fixes both. The cache holds promises rather than resolved values
// so concurrent callers share one parse instead of racing. Entries are large (the AST JSON runs
// ~12x the query text), hence the small limit — the access pattern only ever needs the most recent
// text, so a bigger cache would cost memory without adding hits.
const PARSE_CACHE_LIMIT = 3

interface ParseCacheEntry {
    input: string
    isInternal: boolean
    result: Promise<string>
}

// Keyed by comparing the input directly rather than by building a composite key string: the inputs
// here are up to hundreds of KB, so hashing one on every lookup would be its own cost.
let parseSelectCache: ParseCacheEntry[] = []

export function parseSelect(input: string, isInternal?: boolean): Promise<string> {
    const normalizedIsInternal = !!isInternal
    const hitIndex = parseSelectCache.findIndex((e) => e.isInternal === normalizedIsInternal && e.input === input)
    if (hitIndex !== -1) {
        const [hit] = parseSelectCache.splice(hitIndex, 1)
        parseSelectCache.push(hit) // most-recently-used last
        return hit.result
    }

    const result = getParser()
        .then((parser) => parser.parseSelect(input, normalizedIsInternal))
        .catch((error) => {
            // A failed parse must not be cached — the next call should retry, and parser
            // initialization resets itself on failure.
            parseSelectCache = parseSelectCache.filter((e) => e.result !== result)
            throw error
        })

    parseSelectCache.push({ input, isInternal: normalizedIsInternal, result })
    if (parseSelectCache.length > PARSE_CACHE_LIMIT) {
        parseSelectCache.shift()
    }
    return result
}

export async function parseExpr(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseExpr(input, isInternal)
}

export async function parseOrderExpr(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseOrderExpr(input, isInternal)
}

export async function parseProgram(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseProgram(input, isInternal)
}

export async function parseFullTemplateString(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseFullTemplateString(input, isInternal)
}

export async function parseStringLiteralText(input: string): Promise<string> {
    const parser = await getParser()
    return parser.parseStringLiteralText(input)
}
