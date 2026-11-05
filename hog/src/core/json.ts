import { z } from 'zod'

import { failWith, parseOrThrow, type ParseFailure } from './schema'

// The only module that calls JSON.parse. Its result is `unknown` until a schema checks it, so no
// caller casts JSON to the type it hopes for.

export const JsonObject = z.record(z.string(), z.unknown())

export function parseJson<S extends z.ZodType>(text: string, schema: S, failure: ParseFailure): z.output<S> {
    let raw: unknown
    try {
        raw = JSON.parse(text)
    } catch (error) {
        throw failWith(failure, `Not valid JSON: ${error instanceof Error ? error.message : String(error)}`)
    }
    return parseOrThrow(schema, raw, failure)
}

// For files hog wrote itself and data it can do without: anything it can't read counts as missing.
export function parseJsonOrUndefined<S extends z.ZodType>(text: string, schema: S): z.output<S> | undefined {
    try {
        return schema.safeParse(JSON.parse(text)).data
    } catch {
        return undefined
    }
}

// Keeps integers beyond JavaScript's safe range as their source text, so a ClickHouse UInt64
// survives the round trip to output unchanged, as it does in posthog-cli. Undefined for text that
// isn't JSON. Callers check the result against a schema of their own.
export function parseLosslessJson(text: string): unknown {
    try {
        return JSON.parse(text, (_key, value, context) =>
            typeof value === 'number' &&
            !Number.isSafeInteger(value) &&
            context.source &&
            /^-?\d+$/.test(context.source)
                ? JSON.rawJSON(context.source)
                : value
        )
    } catch {
        return undefined
    }
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
