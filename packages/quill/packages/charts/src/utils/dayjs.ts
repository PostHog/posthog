// Self-contained dayjs setup for hog-charts. Registers only the plugins this library
// needs so it can move into a standalone UI package without depending on PostHog's
// `lib/dayjs`. The wider PostHog app also extends dayjs, but `dayjs.extend` is
// idempotent so calling it again here is safe.

// oxlint-disable-next-line no-restricted-imports
import dayjs, { Dayjs as DayjsOriginal } from 'dayjs'
import customParseFormat from 'dayjs/plugin/customParseFormat'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'

dayjs.extend(customParseFormat)
dayjs.extend(utc)
dayjs.extend(timezone)

export { dayjs }
export interface Dayjs extends DayjsOriginal {}

/** Parse a date string into a Dayjs in the given timezone, browser-tz-independent.
 *
 * - Strings without explicit timezone info ("2026-03-08", "2026-03-08 14:00:00")
 *   are treated as wall-clock time in the given timezone.
 * - Strings with explicit timezone info (trailing "Z" or "±HH:MM") are real instants;
 *   parse them as such and convert into the requested timezone. */
export function parseDateInTimezone(dateStr: string, tz: string): Dayjs {
    const hasExplicitTz = /([Zz]|[+-]\d{2}:?\d{2})$/.test(dateStr)
    try {
        if (hasExplicitTz) {
            const instant = dayjs(dateStr)
            return instant.isValid() ? instant.tz(tz) : dayjs(null)
        }
        return dayjs.tz(dateStr, tz)
    } catch {
        return dayjs(null)
    }
}
