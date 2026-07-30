// Single source of truth for error codes: the metrics layer derives its label set from this
// list, so a code missing here is reported as OTHER. Includes the codes the in-browser player
// emits (NO_SNAPSHOTS, INIT_FAILED, DATA_LOAD_FAILED).
export const RASTERIZATION_ERROR_CODES = [
    'UNKNOWN',
    'OTHER',
    'TIMEOUT',
    'CAPTURE_ABORTED',
    'BEGINFRAME_DEADLOCK',
    'INVALID_INPUT',
    'BLOCK_LISTING_FAILED',
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
