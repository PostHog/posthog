import { DateRange, TrendsFilter, TrendsQuery } from '~/queries/schema/schema-general'
import { isTrendsQuery } from '~/queries/utils'

export const DAYS_IN_WEEK = 7
export const WEEKDAYS: number[] = [1, 2, 3, 4, 5]
export const WEEKENDS: number[] = [6, 7]
export const DAY_LABELS: Record<number, string> = {
    1: 'Mon',
    2: 'Tue',
    3: 'Wed',
    4: 'Thu',
    5: 'Fri',
    6: 'Sat',
    7: 'Sun',
}

export const DAY_LABELS_SINGLE: Record<number, string> = {
    1: 'M',
    2: 'T',
    3: 'W',
    4: 'T',
    5: 'F',
    6: 'S',
    7: 'S',
}

export const ALL_DAY_NUMBERS: number[] = [1, 2, 3, 4, 5, 6, 7]

export function sortDays(days: number[]): number[] {
    return [...days].sort((a, b) => a - b)
}

/** Selected ISO days (1=Mon…7=Sun); [] means all days. Legacy hideWeekends reads as Mon–Fri. */
export function getEffectiveDaysOfWeek(
    dateRange: DateRange | null | undefined,
    trendsFilter: TrendsFilter | null | undefined
): number[] {
    if (dateRange?.daysOfWeek?.length) {
        return sortDays(dateRange.daysOfWeek)
    }
    if (trendsFilter?.hideWeekends) {
        return WEEKDAYS
    }
    return []
}

export function daysOfWeekLabel(days: number[]): string {
    if (days.length === 0 || days.length === DAYS_IN_WEEK) {
        return 'All days'
    }
    if (days.length === WEEKDAYS.length && WEEKDAYS.every((day) => days.includes(day))) {
        return 'Weekdays'
    }
    if (days.length === WEEKENDS.length && WEEKENDS.every((day) => days.includes(day))) {
        return 'Weekends'
    }
    return days.map((day) => DAY_LABELS[day]).join(', ')
}

/**
 * Returns the TrendsQuery patch for a days-of-week selection.
 * Normalises 0 or 7 selected days to null (meaning "all days").
 * Also clears the legacy hideWeekends flag when daysOfWeek takes over.
 */
export function computeDaysOfWeekUpdate(
    days: number[],
    querySource: TrendsQuery | Record<string, any> | null | undefined,
    dateRange: DateRange | null | undefined
): Partial<TrendsQuery> {
    const daysOfWeek = days.length === 0 || days.length === DAYS_IN_WEEK ? null : sortDays(days)
    const update: Partial<TrendsQuery> = { dateRange: { ...dateRange, daysOfWeek } }
    if (isTrendsQuery(querySource) && querySource.trendsFilter?.hideWeekends) {
        update.trendsFilter = { ...querySource.trendsFilter, hideWeekends: undefined }
    }
    return update
}
