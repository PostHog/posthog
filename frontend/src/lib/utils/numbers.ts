export const DEFAULT_DECIMAL_PLACES = 2

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

// taken from https://stackoverflow.com/questions/10420352/converting-file-size-in-bytes-to-human-readable-string/10420404
export const humanizeBytes = (fileSizeInBytes: number | null): string => {
    if (fileSizeInBytes === null) {
        return ''
    }

    let i = -1
    let convertedBytes = fileSizeInBytes
    const byteUnits = ['kB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
    do {
        convertedBytes = convertedBytes / 1024
        i++
    } while (convertedBytes > 1024)

    if (convertedBytes < 0.1) {
        return fileSizeInBytes + ' bytes'
    }
    return convertedBytes.toFixed(2) + ' ' + byteUnits[i]
}

/** Return percentage from number, e.g. 0.234 is 23.4%. */
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

/**
 * Formats the percentage difference between two values for display.
 * Returns null if the result would be NaN or Infinity (e.g., division by zero).
 */
export function formatPercentageDiff(current: number, previous: number): string | null {
    const diff = (current - previous) / previous

    if (!Number.isFinite(diff)) {
        return null
    }

    return diff >= 0 ? `(+${(diff * 100).toFixed(1)}%)` : `(-${(-diff * 100).toFixed(1)}%)`
}

/** Format number with comma as the thousands separator. */
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

export function humanFriendlyLargeNumber(d: number): string {
    if (isNaN(d)) {
        return 'NaN'
    } else if (!isFinite(d)) {
        if (d > 0) {
            return 'inf'
        }
        return '-inf'
    }
    const trillion = 1_000_000_000_000
    const billion = 1_000_000_000
    const million = 1_000_000
    const thousand = 1_000

    // handle positive number only to make life easier
    const prefix = d >= 0 ? '' : '-'
    d = Math.abs(d)

    // round to 3 significant figures
    d = parseFloat(d.toPrecision(3))

    if (d >= trillion) {
        return `${prefix}${(d / trillion).toString()}T`
    } else if (d >= billion) {
        return `${prefix}${(d / billion).toString()}B`
    }
    if (d >= million) {
        return `${prefix}${(d / million).toString()}M`
    }
    if (d >= thousand) {
        return `${prefix}${(d / thousand).toString()}K`
    }
    return `${prefix}${d}`
}

/** Format currency from string with commas and a number of decimal places (defaults to 2). */
export function humanFriendlyCurrency(
    d: string | undefined | number,
    precision: number = DEFAULT_DECIMAL_PLACES
): string {
    if (!d) {
        d = '0.00'
    }

    let number: number
    if (typeof d === 'string') {
        number = parseFloat(d)
    } else {
        number = d
    }

    const validatedPrecision = validateFractionDigits(precision, DEFAULT_DECIMAL_PLACES)
    return `$${number.toLocaleString('en-US', { maximumFractionDigits: validatedPrecision, minimumFractionDigits: validatedPrecision })}`
}

const COMPACT_NUMBER_MAGNITUDES = ['', 'K', 'M', 'B', 'T', 'P', 'E', 'Z', 'Y']

/** Return a number in a compact format, with a SI suffix if applicable.
 *  Server-side equivalent: utils.py#compact_number.
 */
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

export function roundToDecimal(value: number | null, places: number = 2): string {
    if (value === null) {
        return '-'
    }
    return (Math.round(value * 100) / 100).toFixed(places)
}

export const formatPercentage = (x: number, options?: { precise?: boolean; compact?: boolean }): string => {
    let result: string
    if (options?.precise) {
        result = (x / 100).toLocaleString(undefined, { style: 'percent', maximumFractionDigits: 1 })
    } else if (x >= 1000) {
        result = humanFriendlyLargeNumber(x) + '%'
    } else {
        result = (x / 100).toLocaleString(undefined, { style: 'percent', maximumSignificantDigits: 2 })
    }
    if (options?.compact) {
        result = result.replace(/\s+%/, '%')
    }
    return result
}

export function average(input: number[]): number {
    /**
     * Returns the average of an array
     * @param input e.g. [100,50, 75]
     */
    return Math.round((input.reduce((acc, val) => acc + val, 0) / input.length) * 10) / 10
}

export function median(input: number[]): number {
    /**
     * Returns the median of an array
     * @param input e.g. [3,7,10]
     */
    const sorted = [...input].sort((a, b) => a - b)
    const half = Math.floor(sorted.length / 2)

    if (sorted.length % 2) {
        return sorted[half]
    }
    return average([sorted[half - 1], sorted[half]])
}

export function sum(input: number[]): number {
    return input.reduce((a, b) => a + b, 0)
}

export function clamp(value: number, min: number, max: number): number {
    return value > max ? max : value < min ? min : value
}

// Pad numbers with leading zeros
export const zeroPad = (num: number, places: number): string => String(num).padStart(places, '0')
