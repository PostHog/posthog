export class RasterizationError extends Error {
    readonly retryable: boolean

    constructor(message: string, retryable: boolean, cause?: unknown) {
        super(message)
        this.name = 'RasterizationError'
        this.retryable = retryable
        if (cause) {
            this.cause = cause
        }
    }
}
