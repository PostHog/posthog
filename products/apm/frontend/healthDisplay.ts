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
