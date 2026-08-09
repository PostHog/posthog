const DAY_MS = 24 * 60 * 60 * 1000

// Date-only strings, or datetimes at exactly midnight with an optional timezone suffix.
const DAILY_BUCKET_REGEX = /^(\d{4})-(\d{2})-(\d{2})(?:[T ]00:00(?::00(?:\.0+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/

/**
 * Whether the x-axis values form daily, gap-free, ascending buckets. The shared annotations
 * overlay indexes badges by whole-day offsets from the first point, so it only positions them
 * correctly for this shape; callers must hide the overlay for anything else (monthly or hourly
 * buckets, gaps, descending sorts). Uses calendar-day arithmetic in UTC on the raw strings to
 * stay independent of the browser timezone and DST.
 */
export function areConsecutiveDailyDates(dates: string[]): boolean {
    if (dates.length < 2) {
        return false
    }

    let previousUtcDay: number | null = null
    for (const value of dates) {
        const match = DAILY_BUCKET_REGEX.exec(value)
        if (!match) {
            return false
        }
        const utcDay = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
        if (previousUtcDay !== null && utcDay - previousUtcDay !== DAY_MS) {
            return false
        }
        previousUtcDay = utcDay
    }
    return true
}
