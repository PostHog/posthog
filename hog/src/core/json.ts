import type { z } from 'zod'

import { failWith, firstProblem, type ParseFailure } from './schema'

// The only module that calls JSON.parse. Its result is `unknown` until a schema checks it, so no
// caller casts JSON to the type it hopes for.

export type JsonResult<T> =
    | { ok: true; value: T }
    | { ok: false; reason: 'syntax'; problem: string }
    | { ok: false; reason: 'schema'; problem: string; issues: z.core.$ZodIssue[] }

interface JsonOptions {
    // Keeps integers beyond JavaScript's safe range as their source text, so a ClickHouse UInt64
    // survives the round trip to output unchanged, as it does in posthog-cli.
    lossless?: boolean
}

function losslessReviver(_key: string, value: unknown, context: JSONReviverContext): unknown {
    return typeof value === 'number' && !Number.isSafeInteger(value) && context.source && /^-?\d+$/.test(context.source)
        ? JSON.rawJSON(context.source)
        : value
}

export function decodeJson<S extends z.ZodType>(
    text: string,
    schema: S,
    options: JsonOptions = {}
): JsonResult<z.output<S>> {
    let raw: unknown
    try {
        raw = options.lossless ? JSON.parse(text, losslessReviver) : JSON.parse(text)
    } catch (error) {
        const problem = `Not valid JSON: ${error instanceof Error ? error.message : String(error)}`
        return { ok: false, reason: 'syntax', problem }
    }
    const parsed = schema.safeParse(raw)
    return parsed.success
        ? { ok: true, value: parsed.data }
        : { ok: false, reason: 'schema', problem: firstProblem(parsed.error), issues: parsed.error.issues }
}

export function parseJson<S extends z.ZodType>(text: string, schema: S, failure: ParseFailure): z.output<S> {
    const decoded = decodeJson(text, schema)
    if (decoded.ok) {
        return decoded.value
    }
    throw failWith(failure, decoded.problem)
}

// Decodes one escaped JSON string literal, quotes included. Undefined when it isn't one. A JSON
// reader that keeps key order calls this for every escaped string, so it skips zod.
export function decodeJsonString(literal: string): string | undefined {
    try {
        const value: unknown = JSON.parse(literal)
        return typeof value === 'string' ? value : undefined
    } catch {
        return undefined
    }
}

// For files hog wrote itself and data it can do without: anything it can't read counts as missing.
export function parseJsonOrUndefined<S extends z.ZodType>(
    text: string,
    schema: S,
    options?: JsonOptions
): z.output<S> | undefined {
    const decoded = decodeJson(text, schema, options)
    return decoded.ok ? decoded.value : undefined
}
