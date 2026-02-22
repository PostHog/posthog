import { dayjs } from 'lib/dayjs'

export type DetectedInterval = 'hour' | 'day' | 'week' | 'month'

const INTERVAL_SHORTHAND: Record<string, DetectedInterval> = {
    h: 'hour',
    d: 'day',
    w: 'week',
    m: 'month',
}

function normalizeInterval(interval: string): DetectedInterval {
    return INTERVAL_SHORTHAND[interval] ?? (interval as DetectedInterval)
}

/** Detect the time interval from consecutive x-axis date labels. */
export function detectIntervalFromXData(xLabels: string[]): DetectedInterval | null {
    if (xLabels.length < 2) {
        return null
    }
    const first = dayjs(xLabels[0])
    const second = dayjs(xLabels[1])
    if (!first.isValid() || !second.isValid()) {
        return null
    }
    const diffHours = Math.abs(second.diff(first, 'hour'))
    if (diffHours <= 1) {
        return 'hour'
    }
    if (diffHours <= 24) {
        return 'day'
    }
    if (diffHours <= 24 * 7) {
        return 'week'
    }
    return 'month'
}

/**
 * Returns a negative offset from the end of the array indicating where
 * the current (incomplete) time period begins. Returns 0 if all periods
 * are complete. Assumes chronological (ascending) order.
 */
export function computeIncompleteOffset(xLabels: string[], interval: string): number {
    const startDate = dayjs().tz('utc', true).startOf(normalizeInterval(interval))
    const startIndex = xLabels.findIndex((label) => dayjs(label).tz('utc', true) >= startDate)
    if (startIndex !== -1) {
        return startIndex - xLabels.length
    }
    return 0
}

export interface IncompleteRange {
    from: number
    to: number
    count: number
}

/**
 * Finds the contiguous range of incomplete data point indices.
 * Works regardless of sort order (ascending or descending).
 */
export function findIncompleteRange(xLabels: string[], interval: DetectedInterval): IncompleteRange | null {
    if (xLabels.length === 0) {
        return null
    }
    const startDate = dayjs().tz('utc', true).startOf(interval)
    let from = -1
    let to = -1
    for (let i = 0; i < xLabels.length; i++) {
        if (dayjs(xLabels[i]).tz('utc', true) >= startDate) {
            if (from === -1) {
                from = i
            }
            to = i
        }
    }
    if (from === -1) {
        return null
    }
    return { from, to, count: to - from + 1 }
}
