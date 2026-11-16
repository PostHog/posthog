// No imports, so the floating toolbar's entry can recognize these errors without loading the comparison code.

export class FlagOverridesChangedError extends Error {
    constructor() {
        super('The flag overrides changed during the comparison')
        this.name = 'FlagOverridesChangedError'
    }
}

export class CaptureStillRunningError extends Error {
    constructor() {
        super('An earlier page capture is still running')
        this.name = 'CaptureStillRunningError'
    }
}

/** A comparison that stops for one of these reasons worked as designed, so error tracking skips it. */
export function isExpectedComparisonStop(error: unknown): boolean {
    return error instanceof FlagOverridesChangedError || error instanceof CaptureStillRunningError
}
