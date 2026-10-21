const SLOW_TRANSFER_MIN_TOTAL_MS = 5000
const SLOW_TRANSFER_MIN_SHARE = 0.8

export interface QueryTimeBreakdown {
    totalMs: number
    serverMs: number
    transferMs: number
    isTransferSlow: boolean
}

export function getQueryTimeBreakdown(totalMs: number, serverMs: number | null): QueryTimeBreakdown | null {
    if (serverMs === null) {
        return null
    }
    const transferMs = Math.max(totalMs - serverMs, 0)
    return {
        totalMs,
        serverMs,
        transferMs,
        isTransferSlow: totalMs >= SLOW_TRANSFER_MIN_TOTAL_MS && transferMs >= totalMs * SLOW_TRANSFER_MIN_SHARE,
    }
}
