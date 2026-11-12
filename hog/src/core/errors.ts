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

export function wrapFailure(code: string, context: string, cause: unknown, hint?: string): HogError {
    const message = cause instanceof Error ? cause.message : String(cause)
    const serverDetail = cause instanceof HogError ? cause.serverDetail : undefined
    return new HogError(code, `${context}: ${message}`, hint, EXIT_FAILURE, undefined, serverDetail)
}

export const SERVER_DETAIL_HIDDEN = "PostHog's reason is hidden in CI. Run the command outside CI to see it."

export function withServerDetail(message: string, serverDetail: string): string {
    return `${message.replace(/\.$/, '')}: ${serverDetail}`
}

// The text of a failure that a command keeps in its result instead of throwing, such as one endpoint
// of a push. Outside CI it ends with PostHog's reason. In CI it says where to see the reason instead.
export function failureText(error: unknown, isCI: boolean): string {
    const message = error instanceof Error ? error.message : String(error)
    const serverDetail = error instanceof HogError ? error.serverDetail : undefined
    if (serverDetail === undefined) {
        return message
    }
    return isCI ? `${message} ${SERVER_DETAIL_HIDDEN}` : withServerDetail(message, serverDetail)
}
