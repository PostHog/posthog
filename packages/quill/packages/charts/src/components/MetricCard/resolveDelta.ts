import type { ReactNode } from 'react'

export interface MetricChange {
    /** Percent change, so `8` means +8% and `-3` means -3%. The sign sets the pill's direction,
     *  and `goodDirection` on the card decides whether that direction reads as good. */
    value: number
    /** Replaces the formatted `value` in the pill, for example `+1.1 pts` for a change in
     *  percentage points. */
    label?: ReactNode
}

export interface ResolvedDelta {
    value: number
    label: ReactNode
}

export function resolveDelta({
    showChange,
    change,
    fallbackChangePercent,
    formatChange,
}: {
    showChange: boolean
    change: MetricChange | null | undefined
    fallbackChangePercent: number | null
    formatChange: (p: number) => string
}): ResolvedDelta | null {
    if (!showChange) {
        return null
    }
    if (change !== undefined) {
        if (change === null || !Number.isFinite(change.value)) {
            return null
        }
        return {
            value: change.value,
            label: change.label ?? formatChange(change.value),
        }
    }
    if (fallbackChangePercent == null || !Number.isFinite(fallbackChangePercent)) {
        return null
    }
    return {
        value: fallbackChangePercent,
        label: formatChange(fallbackChangePercent),
    }
}
