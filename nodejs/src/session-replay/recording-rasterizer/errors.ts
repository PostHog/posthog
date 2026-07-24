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

/**
 * Transient failures from the object store or the egress proxy sitting in front
 * of it. The most common one is the AWS SDK failing to parse a non-XML response
 * body — an HTML/plaintext error page the store or proxy returned instead of the
 * expected XML — which surfaces as a Smithy deserialization error
 * (`char 'E' is not expected.:1:1 / Deserialization error`). These are worth
 * retrying: the render succeeded and only the upload hit a momentary hiccup.
 */
export function isRetryableStorageError(err: unknown): boolean {
    if (!(err instanceof Error)) {
        return false
    }
    const e = err as Error & {
        code?: string
        $retryable?: unknown
        $metadata?: { httpStatusCode?: number }
        $response?: { statusCode?: number }
    }

    // The AWS SDK tags errors it already considers retryable (throttling, transient 5xx).
    if (e.$retryable != null) {
        return true
    }

    const status = e.$metadata?.httpStatusCode ?? e.$response?.statusCode
    if (typeof status === 'number' && status >= 500) {
        return true
    }

    const message = (e.message ?? '').toLowerCase()
    if (message.includes('deserialization error') || message.includes('is not expected')) {
        return true
    }

    // Transient socket/DNS failures on the S3 or proxy hop.
    const transientNetworkCodes = ['ECONNRESET', 'ECONNREFUSED', 'ETIMEDOUT', 'EPIPE', 'ENOTFOUND', 'EAI_AGAIN']
    if (typeof e.code === 'string' && transientNetworkCodes.includes(e.code)) {
        return true
    }
    if (e.name === 'TimeoutError') {
        return true
    }

    return false
}
