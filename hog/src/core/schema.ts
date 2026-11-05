import type { z } from 'zod'

import { HogError } from './errors'

export interface ParseFailure {
    code: string
    hint?: string
    context?: string
    exitCode?: number
}

// The schemas in hog set their own messages, so the first issue already reads as a sentence. A
// problem inside a document, such as an API answer, starts with the field it is in.
export function firstProblem(error: z.ZodError): string {
    const issue = error.issues[0]
    if (issue === undefined) {
        return 'The value is not valid.'
    }
    return issue.path.length > 0 ? `${issue.path.map(String).join('.')}: ${issue.message}` : issue.message
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
    const problem = firstProblem(parsed.error)
    throw new HogError(
        failure.code,
        failure.context ? `${failure.context} ${problem}` : problem,
        failure.hint,
        failure.exitCode
    )
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
