import type { z } from 'zod'

import { HogError } from './errors'
import { firstProblem, type ParseFailure } from './schema'

// The only module that calls JSON.parse. Its result is `unknown` until a schema checks it, so no
// caller casts JSON to the type it hopes for.

export type JsonResult<T> =
    | { ok: true; value: T }
    // `issues` is empty when the text isn't JSON at all.
    | { ok: false; problem: string; issues: z.core.$ZodIssue[] }

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
        return {
            ok: false,
            problem: `Not valid JSON: ${error instanceof Error ? error.message : String(error)}`,
            issues: [],
        }
    }
    const parsed = schema.safeParse(raw)
    return parsed.success
        ? { ok: true, value: parsed.data }
        : { ok: false, problem: firstProblem(parsed.error), issues: parsed.error.issues }
}

export function parseJson<S extends z.ZodType>(text: string, schema: S, failure: ParseFailure): z.output<S> {
    const decoded = decodeJson(text, schema)
    if (decoded.ok) {
        return decoded.value
    }
    const message = failure.context ? `${failure.context} ${decoded.problem}` : decoded.problem
    throw new HogError(failure.code, message, failure.hint, failure.exitCode)
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
