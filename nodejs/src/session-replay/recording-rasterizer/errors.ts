// Single source of truth for error codes. Includes the codes the in-browser player emits
// (NO_SNAPSHOTS, INIT_FAILED, DATA_LOAD_FAILED). UNKNOWN = a non-RasterizationError was
// thrown; OTHER = a browser-supplied code string we don't recognize (clamped in player.ts).
export const RASTERIZATION_ERROR_CODES = [
    'UNKNOWN',
    'OTHER',
    'TIMEOUT',
    'CAPTURE_ABORTED',
    'TARGET_CLOSED',
    'BEGINFRAME_DEADLOCK',
    'INVALID_INPUT',
    'BLOCK_LISTING_FAILED',
    'S3_UPLOAD_FAILED',
    'S3_UPLOAD_UNDECODABLE_RESPONSE',
    'NO_SNAPSHOTS',
    'INIT_FAILED',
    'DATA_LOAD_FAILED',
] as const

export type RasterizationErrorCode = (typeof RASTERIZATION_ERROR_CODES)[number]

export function toRasterizationErrorCode(code: string): RasterizationErrorCode {
    return (RASTERIZATION_ERROR_CODES as readonly string[]).includes(code) ? (code as RasterizationErrorCode) : 'OTHER'
}

export class RasterizationError extends Error {
    readonly retryable: boolean
    readonly code: RasterizationErrorCode

    constructor(message: string, retryable: boolean, code: RasterizationErrorCode = 'UNKNOWN', cause?: unknown) {
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

// Puppeteer rejects whatever CDP call is in flight when the Chrome target dies mid-render. The
// rejection message names that method ("Protocol error (Page.captureScreenshot): Target closed"),
// so left raw it mints a distinct error-tracking fingerprint per method. Classify it once, at the
// activity boundary, to a single retryable code with a stable message, and keep the original as the
// cause for logs.
export function asRasterizationError(err: unknown): RasterizationError | null {
    if (err instanceof RasterizationError) {
        return err
    }
    const message = err instanceof Error ? err.message : String(err)
    if (message.includes('Target closed')) {
        return new RasterizationError('chrome target closed mid-render', true, 'TARGET_CLOSED', err)
    }
    return null
}
