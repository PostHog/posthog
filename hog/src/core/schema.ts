import type { z } from 'zod'

import { HogError } from './errors'

export interface ParseFailure {
    code: string
    hint?: string
    context?: string
    exitCode?: number
}

const MAX_LISTED_ERRORS = 5

// Every issue zod found, so a person can fix them all in one go. The schemas in hog set their own
// messages, and an issue inside a document, such as an API answer, starts with its field.
export function getErrorMessage(error: z.ZodError): string {
    const messages = error.issues.map((issue) =>
        issue.path.length > 0 ? `${issue.path.map(String).join('.')}: ${issue.message}` : issue.message
    )
    const more = messages.length - MAX_LISTED_ERRORS
    const listed = messages.slice(0, MAX_LISTED_ERRORS).join('; ')
    return more > 0 ? `${listed}; and ${more} more` : listed || 'The value is not valid.'
}

export function validationError(schema: z.ZodType, raw: unknown): string | undefined {
    const parsed = schema.safeParse(raw)
    return parsed.success ? undefined : getErrorMessage(parsed.error)
}

export function parseOrThrow<S extends z.ZodType>(schema: S, raw: unknown, failure: ParseFailure): z.output<S> {
    const parsed = schema.safeParse(raw)
    if (parsed.success) {
        return parsed.data
    }
    const message = getErrorMessage(parsed.error)
    throw new HogError(
        failure.code,
        failure.context ? `${failure.context} ${message}` : message,
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
