export const VM_INIT_MAX_RETRIES = 5
export const INITIALIZATION_RETRY_MULTIPLIER = 2
export const INITIALIZATION_RETRY_BASE_MS = 5000

export function getNextRetryMs(attemptsCount: number): number {
    const nextRetryMs = INITIALIZATION_RETRY_MULTIPLIER ** (attemptsCount - 1) * INITIALIZATION_RETRY_BASE_MS
    return nextRetryMs
}
