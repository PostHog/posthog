const UNITS: [number, string][] = [
    [1_000_000_000, 'B'],
    [1_000_000, 'M'],
    [1_000, 'k'],
    [1, ''],
]

export function todayNumber(value: number): string {
    const size = Math.abs(value)
    const found = UNITS.findIndex(([threshold]) => size >= threshold)
    for (let index = found === -1 ? UNITS.length - 1 : found; index >= 0; index--) {
        const [threshold, suffix] = UNITS[index]
        const scaled = value / threshold
        const digits = threshold === 1 ? (Number.isInteger(value) ? 0 : 1) : Math.abs(scaled) < 100 ? 1 : 0
        const text = scaled.toFixed(digits).replace(/\.0$/, '')
        if (index === 0 || Math.abs(Number(text)) < 1000) {
            return `${text}${suffix}`
        }
    }
    return String(value)
}

export function todayChangeText(change: number, unit: '%' | 'pp', decimals = 0): string {
    const places = unit === 'pp' ? 1 : decimals
    const scale = 10 ** places
    const rounded = Math.round(change * scale) / scale
    const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : ''
    const size = Math.abs(rounded).toLocaleString('en-US', { maximumFractionDigits: places })
    if (unit === 'pp') {
        return `${sign}${size} pp`
    }
    return rounded === 0 ? '0%' : `${sign}${size}%`
}
