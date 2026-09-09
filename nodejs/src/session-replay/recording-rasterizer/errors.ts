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
    'RECORDING_TOO_LARGE',
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

// Puppeteer rejects whatever CDP call is in flight when the Chrome target dies mid-render. Some of
// those rejections name the CDP method ("Protocol error (Page.captureScreenshot): Session closed.
// Most likely the page has been closed."), so left raw they mint a distinct error-tracking
// fingerprint per method. Classify once, at the activity boundary, to a single retryable code with a
// stable message, keeping the original as the cause for logs.
//
// Match on the error name first: puppeteer raises every one of these as TargetCloseError but words
// the message six different ways ("Target closed", "Session closed. Most likely the ... has been
// closed.", "Page closed!", "Frame detached."). Matching one wording is what let the earlier
// variants through. The message checks stay as a fallback for a wrapped or re-thrown rejection that
// lost the prototype.
export function asRasterizationError(err: unknown): RasterizationError | null {
    if (err instanceof RasterizationError) {
        return err
    }
    const name = err instanceof Error ? err.name : ''
    const message = err instanceof Error ? err.message : String(err)
    if (name === 'TargetCloseError' || message.includes('Target closed') || message.includes('Session closed')) {
        return new RasterizationError('chrome target closed mid-render', true, 'TARGET_CLOSED', err)
    }
    return null
}
