// Self-contained number/colour/currency formatting helpers. hog-charts is intended to
// move into a standalone UI library, so this file deliberately has no PostHog imports —
// only standard browser APIs.

const DEFAULT_DECIMAL_PLACES = 2
const COMPACT_NUMBER_MAGNITUDES = ['', 'K', 'M', 'B', 'T', 'P', 'E', 'Z', 'Y']

function validateFractionDigits(maximumFractionDigits: number, fallback: number): number {
    if (
        isNaN(maximumFractionDigits) ||
        !Number.isInteger(maximumFractionDigits) ||
        maximumFractionDigits < 0 ||
        maximumFractionDigits > 100
    ) {
        return fallback
    }
    return maximumFractionDigits
}

export function humanFriendlyNumber(
    d: number,
    maximumFractionDigits: number = DEFAULT_DECIMAL_PLACES,
    minimumFractionDigits: number = 0
): string {
    return d.toLocaleString('en-US', {
        maximumFractionDigits: validateFractionDigits(maximumFractionDigits, DEFAULT_DECIMAL_PLACES),
        minimumFractionDigits: validateFractionDigits(minimumFractionDigits, 0),
    })
}

export function humanFriendlyCurrency(
    d: string | undefined | number,
    precision: number = DEFAULT_DECIMAL_PLACES
): string {
    if (!d) {
        d = '0.00'
    }
    const number = typeof d === 'string' ? parseFloat(d) : d
    const validatedPrecision = validateFractionDigits(precision, DEFAULT_DECIMAL_PLACES)
    return `$${number.toLocaleString('en-US', { maximumFractionDigits: validatedPrecision, minimumFractionDigits: validatedPrecision })}`
}

export function humanFriendlyDuration(
    d: string | number | null | undefined,
    {
        maxUnits,
        secondsPrecision,
        secondsFixed,
    }: { maxUnits?: number; secondsPrecision?: number; secondsFixed?: number } = {}
): string {
    if (d === '' || d === null || d === undefined || maxUnits === 0) {
        return ''
    }
    d = Number(d)
    if (d < 0) {
        return `-${humanFriendlyDuration(-d, { maxUnits, secondsPrecision, secondsFixed })}`
    }
    if (d === 0) {
        return `0s`
    }
    if (d < 1) {
        return `${Math.round(d * 1000)}ms`
    }
    if (d < 60) {
        if (secondsPrecision != null) {
            return `${parseFloat(d.toPrecision(secondsPrecision))}s`
        }
        return `${parseFloat(d.toFixed(secondsFixed ?? 0))}s`
    }

    const days = Math.floor(d / 86400)
    const h = Math.floor((d % 86400) / 3600)
    const m = Math.floor((d % 3600) / 60)
    const s = Math.floor((d % 3600) % 60)

    const dayDisplay = days > 0 ? days + 'd' : ''
    const hDisplay = h > 0 ? h + 'h' : ''
    const mDisplay = m > 0 ? m + 'm' : ''
    const sDisplay = s > 0 ? s + 's' : hDisplay || mDisplay ? '' : '0s'

    let units: string[] = []
    if (days > 0) {
        units = [dayDisplay, hDisplay].filter(Boolean)
    } else {
        units = [hDisplay, mDisplay, sDisplay].filter(Boolean)
    }
    return units.slice(0, maxUnits ?? undefined).join(' ')
}

export function percentage(
    division: number,
    maximumFractionDigits: number = DEFAULT_DECIMAL_PLACES,
    fixedPrecision: boolean = false
): string {
    if (division === Infinity) {
        return '∞%'
    }
    const maxDigits = validateFractionDigits(maximumFractionDigits, DEFAULT_DECIMAL_PLACES)
    return division.toLocaleString('en-US', {
        style: 'percent',
        maximumFractionDigits: maxDigits,
        minimumFractionDigits: fixedPrecision ? maxDigits : undefined,
    })
}

export function compactNumber(value: number | null): string {
    if (value === null) {
        return '-'
    }
    value = parseFloat(value.toPrecision(3))
    let magnitude = 0
    while (Math.abs(value) >= 1000) {
        magnitude++
        value /= 1000
    }
    return magnitude > 0 ? `${value} ${COMPACT_NUMBER_MAGNITUDES[magnitude]}` : value.toString()
}

/** Format an amount as currency, prefixed/suffixed by the locale-derived symbol.
 *  Accepts any string the runtime `Intl.NumberFormat` accepts as a currency code. */
export function formatCurrency(amount: number, currency: string): string {
    const { symbol, isPrefix } = getCurrencySymbol(currency)
    return `${isPrefix ? symbol : ''}${humanFriendlyNumber(amount, 2, 2)}${isPrefix ? '' : ' ' + symbol}`
}

function getCurrencySymbol(currency: string): { symbol: string; isPrefix: boolean } {
    const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency })
    const parts = formatter.formatToParts(0)
    const symbol = parts.find((part) => part.type === 'currency')?.value
    const isPrefix = symbol ? parts[0].type === 'currency' : true
    return { symbol: symbol ?? currency, isPrefix }
}

function hexToRGB(hex: string): { r: number; g: number; b: number; a: number } {
    hex = hex.replace(/^#/, '')
    if (hex.length === 3 || hex.length === 4) {
        hex = hex
            .split('')
            .map((char) => char + char)
            .join('')
    }
    if (hex.length !== 6 && hex.length !== 8) {
        return { r: 0, g: 0, b: 0, a: 0 }
    }
    const r = parseInt(hex.slice(0, 2), 16)
    const g = parseInt(hex.slice(2, 4), 16)
    const b = parseInt(hex.slice(4, 6), 16)
    const a = hex.length === 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1
    return { r, g, b, a }
}

export function hexToRGBA(hex: string, alpha = 1): string {
    const { r, g, b } = hexToRGB(hex)
    return `rgba(${[r, g, b, alpha].join(',')})`
}
