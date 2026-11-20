import type { HealthStatusEnumApi } from './generated/api.schemas'

export const STATUS_LABEL: Record<HealthStatusEnumApi, string> = {
    good: 'Healthy',
    warning: 'Watch',
    serious: 'Failing',
    critical: 'Confirmed',
}

export const STATUS_TAG: Record<HealthStatusEnumApi, 'success' | 'warning' | 'danger'> = {
    good: 'success',
    warning: 'warning',
    serious: 'danger',
    critical: 'danger',
}

export function formatRate(perSecond: number | null): string {
    if (perSecond === null) {
        return '—'
    }
    if (perSecond >= 1000) {
        return `${(perSecond / 1000).toFixed(1)}k/s`
    }
    if (perSecond >= 10) {
        return `${Math.round(perSecond)}/s`
    }
    if (perSecond >= 0.1) {
        return `${perSecond.toFixed(1)}/s`
    }
    return `${(perSecond * 60).toFixed(1)}/min`
}

/** The one unit a table shows every request rate in, so rows can be compared at a glance. */
export type RateUnit = 'req/s' | 'req/min'

/** Per second when any row reaches 0.1 requests a second, per minute when every row is quieter. */
export function tableRateUnit(perSecondRates: (number | null)[]): RateUnit {
    return perSecondRates.some((rate) => rate !== null && rate >= 0.1) ? 'req/s' : 'req/min'
}

/** A request rate as a bare number in the table's unit; the column header carries the unit. */
export function formatRateIn(perSecond: number | null, unit: RateUnit): string {
    if (perSecond === null) {
        return '—'
    }
    const value = unit === 'req/s' ? perSecond : perSecond * 60
    if (value === 0) {
        return '0'
    }
    if (value >= 1000) {
        return `${(value / 1000).toFixed(1)}k`
    }
    if (value >= 10) {
        return `${Math.round(value)}`
    }
    if (value >= 0.1) {
        return value.toFixed(1)
    }
    if (value >= 0.01) {
        return value.toFixed(2)
    }
    return '<0.01'
}

export function formatPercent(fraction: number | null): string {
    if (fraction === null) {
        return '—'
    }
    const pct = fraction * 100
    return `${pct.toFixed(pct >= 10 ? 0 : pct >= 1 ? 1 : 2)}%`
}

export function formatMs(ms: number | null): string {
    if (ms === null) {
        return '—'
    }
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

// Health responses cached before apdex shipped have no score at all, so treat undefined like null.
export function formatApdex(score: number | null | undefined): string {
    return score === null || score === undefined ? '—' : score.toFixed(2)
}

export function compareNullable(a: number | null, b: number | null): number {
    return (a ?? -Infinity) - (b ?? -Infinity) || 0
}

export function matchesSearch(search: string, ...fields: string[]): boolean {
    const needle = search.trim().toLowerCase()
    return !needle || fields.some((field) => field.toLowerCase().includes(needle))
}
