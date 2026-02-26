import { Dayjs, dayjs } from 'lib/dayjs'

export type WindowSize = '5m' | '10m' | '1h'
export type WindowDirection = 'before' | 'around' | 'after'

const WINDOW_MINUTES: Record<WindowSize, number> = {
    '5m': 5,
    '10m': 10,
    '1h': 60,
}

const FALLBACK_FORMATS = ['MM/DD/YYYY', 'YYYYMMDD', 'MM/DD/YYYY HH:mm']

const MAX_FUTURE_MS = 365 * 24 * 60 * 60 * 1000

export function parseTimestampInput(input: string): Dayjs | null {
    const trimmed = input.trim()
    if (!trimmed) {
        return null
    }

    let parsed: Dayjs | null = null

    // Numeric-only: unix timestamps (require at least 9 digits for seconds)
    if (/^\d+(\.\d+)?$/.test(trimmed)) {
        // 8-digit numeric strings like 20240115 should try YYYYMMDD first
        if (trimmed.length === 8) {
            const compact = dayjs(trimmed, 'YYYYMMDD', true)
            if (compact.isValid()) {
                parsed = compact
            }
        }

        if (!parsed?.isValid()) {
            const num = parseFloat(trimmed)
            if (trimmed.includes('.') || (trimmed.length >= 9 && trimmed.length <= 10)) {
                parsed = dayjs(num * 1000)
            } else if (trimmed.length >= 11) {
                parsed = dayjs(num)
            }
        }
    }

    // Try dayjs native parsing (ISO 8601, YYYY-MM-DD, YYYY-MM-DD HH:mm:ss, etc.)
    if (!parsed?.isValid()) {
        const native = dayjs(trimmed)
        if (native.isValid()) {
            parsed = native
        }
    }

    // Fallback: strict parsing with common formats
    if (!parsed?.isValid()) {
        for (const fmt of FALLBACK_FORMATS) {
            const attempt = dayjs(trimmed, fmt, true)
            if (attempt.isValid()) {
                parsed = attempt
                break
            }
        }
    }

    if (!parsed?.isValid()) {
        return null
    }

    // Reject dates before year 2000 (no useful data that old)
    if (parsed.year() < 2000) {
        return null
    }

    // Reject dates unreasonably far in the future
    if (parsed.valueOf() > Date.now() + MAX_FUTURE_MS) {
        return null
    }

    return parsed
}

export function computeDateRange(
    timestamp: Dayjs,
    windowSize: WindowSize,
    direction: WindowDirection
): { date_from: string; date_to: string } {
    const minutes = WINDOW_MINUTES[windowSize]
    const fmt = 'YYYY-MM-DDTHH:mm:ss'

    switch (direction) {
        case 'before':
            return {
                date_from: timestamp.subtract(minutes, 'minute').format(fmt),
                date_to: timestamp.format(fmt),
            }
        case 'after':
            return {
                date_from: timestamp.format(fmt),
                date_to: timestamp.add(minutes, 'minute').format(fmt),
            }
        case 'around':
        default:
            return {
                date_from: timestamp.subtract(minutes / 2, 'minute').format(fmt),
                date_to: timestamp.add(minutes / 2, 'minute').format(fmt),
            }
    }
}
