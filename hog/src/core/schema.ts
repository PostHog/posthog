import { HogError } from './errors'

// zod schemas have this shape, so hog's parsing helpers don't depend on zod's types.
export interface Schema<T> {
    safeParse(raw: unknown): { success: true; data: T } | { success: false; error: { issues: readonly SchemaIssue[] } }
}

export interface SchemaIssue {
    readonly path: readonly PropertyKey[]
    readonly message: string
}

export interface ParseFailure {
    code: string
    hint?: string
    context?: string
    exitCode?: number
}

const MAX_LISTED_ERRORS = 5

// Every issue zod found, so a person can fix them all in one go. The schemas in hog set their own
// messages, and an issue inside a document, such as an API answer, starts with its field.
export function getErrorMessage(error: { issues: readonly SchemaIssue[] }): string {
    const messages = error.issues.map((issue) =>
        issue.path.length > 0 ? `${issue.path.map(String).join('.')}: ${issue.message}` : issue.message
    )
    const more = messages.length - MAX_LISTED_ERRORS
    const listed = messages.slice(0, MAX_LISTED_ERRORS).join('; ')
    return more > 0 ? `${listed}; and ${more} more` : listed || 'The value is not valid.'
}

export function validationError(schema: Schema<unknown>, raw: unknown): string | undefined {
    const parsed = schema.safeParse(raw)
    return parsed.success ? undefined : getErrorMessage(parsed.error)
}

export function parseOrThrow<T>(schema: Schema<T>, raw: unknown, failure: ParseFailure): T {
    const parsed = schema.safeParse(raw)
    if (parsed.success) {
        return parsed.data
    }
    throw failWith(failure, getErrorMessage(parsed.error))
}

export function failWith(failure: ParseFailure, message: string): HogError {
    const full = failure.context ? `${failure.context} ${message}` : message
    return new HogError(failure.code, full, failure.hint, failure.exitCode)
}
