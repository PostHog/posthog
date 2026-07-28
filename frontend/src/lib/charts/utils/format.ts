import { compactNumber } from 'lib/utils/numbers'

import type { AxisFormat, ChartSeriesSettings } from '../types'

/** Formats a raw data value with a column's per-series display settings (style, decimal places,
 *  prefix/suffix). Shared by the data viz results table and chart tooltips/labels/ticks. */
export const formatDataWithSettings = (
    data: number | string | null | object,
    settings?: ChartSeriesSettings
): string | object | null => {
    if (data === null || Number.isNaN(data)) {
        return null
    }

    if (typeof data === 'object') {
        return data
    }

    const decimalPlaces = settings?.formatting?.decimalPlaces

    let dataAsString = `${data}`

    if (typeof data === 'number') {
        dataAsString = `${decimalPlaces ? data.toFixed(decimalPlaces) : data}`

        if (settings?.formatting?.style === 'number') {
            dataAsString = data.toLocaleString(undefined, { maximumFractionDigits: decimalPlaces })
        }

        if (settings?.formatting?.style === 'short') {
            dataAsString = compactNumber(data)
        }

        if (settings?.formatting?.style === 'percent') {
            dataAsString = `${data.toLocaleString(undefined, { maximumFractionDigits: decimalPlaces })}%`
        }
    }

    if (settings?.formatting?.prefix) {
        dataAsString = `${settings.formatting.prefix}${dataAsString}`
    }

    if (settings?.formatting?.suffix) {
        dataAsString = `${dataAsString}${settings.formatting.suffix}`
    }

    return dataAsString
}

export function formatValue(
    value: number,
    format: AxisFormat = 'number',
    options?: { prefix?: string; suffix?: string; decimalPlaces?: number }
): string {
    const prefix = options?.prefix ?? ''
    const suffix = options?.suffix ?? ''
    const decimals = options?.decimalPlaces

    let formatted: string

    switch (format) {
        case 'number':
            formatted = formatNumber(value, decimals)
            break
        case 'compact':
            formatted = formatCompact(value, decimals)
            break
        case 'percent':
            formatted = formatPercent(value, decimals)
            break
        case 'duration':
            formatted = formatDuration(value)
            break
        case 'duration_ms':
            formatted = formatDuration(value / 1000)
            break
        case 'date':
            formatted = formatDate(value)
            break
        case 'datetime':
            formatted = formatDateTime(value)
            break
        case 'none':
            formatted = String(value)
            break
        default:
            formatted = formatNumber(value, decimals)
    }

    return `${prefix}${formatted}${suffix}`
}

function formatNumber(value: number, decimalPlaces?: number): string {
    return value.toLocaleString('en-US', {
        minimumFractionDigits: decimalPlaces,
        maximumFractionDigits: decimalPlaces ?? 2,
    })
}

function formatCompact(value: number, decimalPlaces?: number): string {
    const abs = Math.abs(value)
    const dp = decimalPlaces ?? 1

    if (abs >= 1_000_000_000) {
        return `${(value / 1_000_000_000).toFixed(dp)}B`
    }
    if (abs >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(dp)}M`
    }
    if (abs >= 1_000) {
        return `${(value / 1_000).toFixed(dp)}K`
    }
    return formatNumber(value, decimalPlaces)
}

function formatPercent(value: number, decimalPlaces?: number): string {
    return `${(value * 100).toFixed(decimalPlaces ?? 1)}%`
}

function formatDuration(seconds: number): string {
    const abs = Math.abs(seconds)
    const sign = seconds < 0 ? '-' : ''

    if (abs < 60) {
        return `${sign}${abs.toFixed(1)}s`
    }
    if (abs < 3600) {
        const m = Math.floor(abs / 60)
        const s = Math.round(abs % 60)
        return `${sign}${m}m ${s}s`
    }
    if (abs < 86400) {
        const h = Math.floor(abs / 3600)
        const m = Math.round((abs % 3600) / 60)
        return `${sign}${h}h ${m}m`
    }
    const d = Math.floor(abs / 86400)
    const h = Math.round((abs % 86400) / 3600)
    return `${sign}${d}d ${h}h`
}

function formatDate(timestamp: number): string {
    return new Date(timestamp).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
    })
}

function formatDateTime(timestamp: number): string {
    return new Date(timestamp).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    })
}
