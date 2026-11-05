export const EXIT_FAILURE = 1
export const EXIT_USAGE = 2

// A failure hog reports to the caller. `code` is stable and machine-readable, so agents and
// scripts can branch on it; `message` and `hint` are for people.
export class HogError extends Error {
    constructor(
        readonly code: string,
        message: string,
        readonly hint?: string,
        readonly exitCode = EXIT_FAILURE
    ) {
        super(message)
        this.name = 'HogError'
    }

    withHint(hint: string): HogError {
        return new HogError(this.code, this.message, hint, this.exitCode)
    }
}
