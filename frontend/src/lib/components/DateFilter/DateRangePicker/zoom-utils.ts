import { DEFAULT_DATE_RANGE_PICKER_OPTIONS } from 'lib/components/DateFilter/DateRangePicker/constants'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

// Unit letters follow PostHog's date convention: uppercase `M` is minute, lowercase `m` is month
const RELATIVE_DATE_REGEX = /(^-?)(\d+)([sMhdwmqy])$/

const zoomDateRelative = (date: string | null | undefined, multiplier: number): string | null => {
    if (!date) {
        return null
    }
    const match = date.match(RELATIVE_DATE_REGEX)
    if (match) {
        // Multiply the value, rounding to a whole unit (and at least 1) so the result stays a valid relative expression
        const [, sign, amount, unit] = match
        const newAmount = Math.max(Math.round(parseInt(amount) * multiplier), 1)
        return `${sign}${newAmount}${unit}`
    }
    return null
}

export const zoomDateRange = (
    dateRange: { date_from?: string | null; date_to?: string | null },
    multiplier: number
): { date_from?: string | null; date_to?: string | null } => {
    const now = dayjs()
    // If only date_from is set and is relative we can do a nicer zoom function
    if (dateRange.date_from && !dateRange.date_to) {
        const newDateFrom = zoomDateRelative(dateRange.date_from, multiplier)
        if (newDateFrom) {
            return {
                date_from: newDateFrom,
                date_to: null,
            }
        }
    }

    const start = dateRange.date_from
        ? (dateStringToDayJs(dateRange.date_from) ?? now.subtract(1, 'hour'))
        : now.subtract(1, 'hour')
    const end = dateRange.date_to ? (dateStringToDayJs(dateRange.date_to) ?? now) : now

    // Use a minimum of 1 minute when diff is 0 (same from/to timestamps) to allow zooming out
    const diffMins = Math.max(end.diff(start, 'minutes'), 1)
    const centerDate = start.add(diffMins * 0.5, 'minutes')

    const newStart = centerDate.subtract(diffMins * 0.5 * multiplier, 'minutes')
    const newEnd = centerDate.add(diffMins * 0.5 * multiplier, 'minutes')

    return {
        date_from: newStart.format('YYYY-MM-DDTHH:mm:ss.SSSZ'),
        date_to: (newEnd.isAfter(now) ? now : newEnd).format('YYYY-MM-DDTHH:mm:ss.SSSZ'),
    }
}

/** Jumps straight to the next wider picker preset (e.g. `-15M` -> `-1h`) rather than doubling
 * the current range, so a single click from a narrow range lands somewhere actually useful.
 * Falls back to a plain 2x zoom for custom ranges or a range already at the widest preset. */
export const expandToNextDateRangePreset = (dateRange: {
    date_from?: string | null
    date_to?: string | null
}): { date_from?: string | null; date_to?: string | null } => {
    if (dateRange.date_from && !dateRange.date_to) {
        const presetIndex = DEFAULT_DATE_RANGE_PICKER_OPTIONS.findIndex(
            (option) => option.values[0] === dateRange.date_from
        )
        const nextPreset = presetIndex >= 0 ? DEFAULT_DATE_RANGE_PICKER_OPTIONS[presetIndex + 1] : undefined
        if (nextPreset) {
            return { date_from: nextPreset.values[0], date_to: null }
        }
    }
    return zoomDateRange(dateRange, 2)
}
