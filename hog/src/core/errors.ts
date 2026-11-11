export const EXIT_FAILURE = 1
export const EXIT_USAGE = 2

// A failure hog reports to the caller. `code` is stable and machine-readable, so agents and
// scripts can branch on it; `message` and `hint` are for people. Agents also get `details`.
// `serverDetail` is PostHog's own reason for refusing a request. It stays out of `message`, because
// it can repeat values from the request, and `Output` shows it only outside CI, where logs can be public.
export class HogError extends Error {
    constructor(
        readonly code: string,
        message: string,
        readonly hint?: string,
        readonly exitCode = EXIT_FAILURE,
        readonly details?: Readonly<Record<string, unknown>>,
        readonly serverDetail?: string
    ) {
        super(message)
        this.name = 'HogError'
    }

    withHint(hint: string): HogError {
        return new HogError(this.code, this.message, hint, this.exitCode, this.details, this.serverDetail)
    }
}

// Puts `context` in front of the cause's message and keeps the cause's `serverDetail`.
export function wrapFailure(code: string, context: string, cause: unknown, hint?: string): HogError {
    const message = cause instanceof Error ? cause.message : String(cause)
    const serverDetail = cause instanceof HogError ? cause.serverDetail : undefined
    return new HogError(code, `${context}: ${message}`, hint, EXIT_FAILURE, undefined, serverDetail)
}
