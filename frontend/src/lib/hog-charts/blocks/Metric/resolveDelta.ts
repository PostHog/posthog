import React from 'react'

export interface MetricChange {
    value: number
    label?: React.ReactNode
}

export interface ResolvedDelta {
    value: number
    label: React.ReactNode
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
        if (change === null) {
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
