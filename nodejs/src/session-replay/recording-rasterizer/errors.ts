export class RasterizationError extends Error {
    readonly retryable: boolean
    readonly code: string

    constructor(message: string, retryable: boolean, code = 'UNKNOWN', cause?: unknown) {
        super(message)
        this.name = 'RasterizationError'
        this.retryable = retryable
        this.code = code
        if (cause) {
            this.cause = cause
        }
    }

    toJSON(): Record<string, unknown> {
        return {
            name: this.name,
            message: this.message,
            retryable: this.retryable,
            code: this.code,
        }
    }
}
