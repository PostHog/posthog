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
    return unit === 0 ? `${sign}${Math.round(value)} B` : `${sign}${value.toFixed(2)} ${BYTE_UNITS[unit]}`
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
