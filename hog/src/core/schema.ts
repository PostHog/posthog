import type { z } from 'zod'

import { HogError } from './errors'

export interface ParseFailure {
    code: string
    hint?: string
    context?: string
    exitCode?: number
}

// The schemas in hog set their own messages, so the first issue already reads as a sentence.
export function firstProblem(error: z.ZodError): string {
    return error.issues[0]?.message ?? 'The value is not valid.'
}

export function problemWith(schema: z.ZodType, raw: unknown): string | undefined {
    const parsed = schema.safeParse(raw)
    return parsed.success ? undefined : firstProblem(parsed.error)
}

export function parseOrThrow<S extends z.ZodType>(schema: S, raw: unknown, failure: ParseFailure): z.output<S> {
    const parsed = schema.safeParse(raw)
    if (parsed.success) {
        return parsed.data
    }
    throw failWith(failure, firstProblem(parsed.error))
}

export function failWith(failure: ParseFailure, problem: string): HogError {
    const message = failure.context ? `${failure.context} ${problem}` : problem
    return new HogError(failure.code, message, failure.hint, failure.exitCode)
}

// For stored data, where a value hog doesn't recognize reads as missing instead of failing the command.
export function parseOrUndefined<S extends z.ZodType>(schema: S, raw: unknown): z.output<S> | undefined {
    const parsed = schema.safeParse(raw)
    return parsed.success ? parsed.data : undefined
}

export function parser<S extends z.ZodType>(
    schema: S,
    defaults: ParseFailure
): (raw: unknown, failure?: Partial<ParseFailure>) => z.output<S> {
    return (raw, failure) => parseOrThrow(schema, raw, { ...defaults, ...failure })
}
