const BYTE_UNITS = ['kB', 'MB', 'GB', 'TB', 'PB']

/** Formats bytes in powers of 1000, the units billing counts logs in. */
export function formatBytes(bytes: number): string {
    if (bytes < 1000) {
        return `${bytes} B`
    }
    let value = bytes
    let unit = -1
    while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
        value /= 1000
        unit++
    }
    return `${value.toFixed(unit >= 2 ? 2 : 1)} ${BYTE_UNITS[unit]}`
}

/** The share of a total as a percentage, or null when there is nothing to share. */
export function formatShare(value: number, total: number): string | null {
    if (total <= 0 || value <= 0) {
        return null
    }
    const pct = (value / total) * 100
    if (pct < 0.1) {
        return '<0.1%'
    }
    return `${pct.toFixed(pct >= 10 ? 0 : 1)}%`
}
