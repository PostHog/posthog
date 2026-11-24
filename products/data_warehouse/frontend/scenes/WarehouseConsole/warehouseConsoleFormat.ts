import { dayjs } from 'lib/dayjs'

const BYTE_UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']

export const GIB = 1024 ** 3
export const TIB = 1024 ** 4

/** Formats a byte count with binary units, as the warehouse bills them. */
export function formatBytes(bytes: number | null | undefined): string {
    if (bytes == null || !Number.isFinite(bytes)) {
        return '-'
    }
    let value = Math.abs(bytes)
    let unit = 0
    while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
        value /= 1024
        unit += 1
    }
    const sign = bytes < 0 ? '-' : ''
    return unit === 0 ? `${sign}${Math.round(value)} B` : `${sign}${Number(value.toFixed(2))} ${BYTE_UNITS[unit]}`
}

/** The API sends money and fractional quantities as decimal strings. */
export function parseDecimal(value: string | number | null | undefined): number {
    if (value == null) {
        return 0
    }
    const parsed = typeof value === 'number' ? value : Number.parseFloat(value)
    return Number.isFinite(parsed) ? parsed : 0
}

export function formatUsd(value: string | number | null | undefined): string {
    const amount = parseDecimal(value)
    if (amount > 0 && amount < 0.01) {
        return '< $0.01'
    }
    return amount.toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })
}

/** A count with thousands separators: 3,095. */
export function formatCount(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '-' : Math.round(value).toLocaleString('en-US')
}

/** A duration in the shortest readable form: 676 ms, 7.2 s, 2 m 05 s, 1 h 05 m. */
export function formatDuration(ms: number | null | undefined): string {
    if (ms == null || !Number.isFinite(ms)) {
        return '-'
    }
    if (ms < 1000) {
        return `${Math.round(ms)} ms`
    }
    const seconds = ms / 1000
    if (seconds < 60) {
        return `${Number(seconds.toFixed(1))} s`
    }
    const wholeSeconds = Math.round(seconds)
    const minutes = Math.floor(wholeSeconds / 60)
    if (minutes < 60) {
        return `${minutes} m ${String(wholeSeconds % 60).padStart(2, '0')} s`
    }
    return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} m`
}

/** "2 hours ago". Pair it with `formatAbsoluteTime` in a title so the exact time shows on hover. */
export function formatRelativeTime(iso: string | null | undefined): string {
    return iso ? dayjs(iso).fromNow() : '-'
}

export function formatAbsoluteTime(iso: string | null | undefined): string {
    return iso ? dayjs(iso).format('YYYY-MM-DD HH:mm:ss') : ''
}

export function formatPercent(fraction: number): string {
    return `${Math.round(fraction * 100)}%`
}

export interface ByteUnit {
    divisor: number
    label: string
}

/** The binary unit a chart axis counts in, so its tick values are round numbers in that unit (0, 100, 200 GiB). */
export function chartByteUnit(maxBytes: number): ByteUnit {
    let unit = 0
    let divisor = 1
    while (maxBytes / divisor >= 1024 && unit < BYTE_UNITS.length - 1) {
        divisor *= 1024
        unit += 1
    }
    return { divisor, label: BYTE_UNITS[unit] }
}

export function formatAxisBytes(valueInUnit: number, unit: ByteUnit): string {
    return `${Number(valueInUnit.toFixed(2))} ${unit.label}`
}

/** Meter color: warning from 80 percent of an allowance, destructive from 100. */
export function meterVariant(percent: number | null): 'default' | 'warning' | 'destructive' {
    return percent == null ? 'default' : percent >= 100 ? 'destructive' : percent >= 80 ? 'warning' : 'default'
}
