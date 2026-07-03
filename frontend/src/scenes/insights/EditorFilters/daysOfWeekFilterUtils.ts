import { DateRange, TrendsFilter } from '~/queries/schema/schema-general'

export const WEEKDAYS: number[] = [1, 2, 3, 4, 5]
export const DAY_LABELS: Record<number, string> = {
    1: 'Mon',
    2: 'Tue',
    3: 'Wed',
    4: 'Thu',
    5: 'Fri',
    6: 'Sat',
    7: 'Sun',
}

/** Selected ISO days (1=Mon…7=Sun); [] means all days. Legacy hideWeekends reads as Mon–Fri. */
export function getEffectiveDaysOfWeek(
    dateRange: DateRange | null | undefined,
    trendsFilter: TrendsFilter | null | undefined
): number[] {
    if (dateRange?.daysOfWeek?.length) {
        return [...dateRange.daysOfWeek].sort()
    }
    if (trendsFilter?.hideWeekends) {
        return WEEKDAYS
    }
    return []
}

export function daysOfWeekLabel(days: number[]): string {
    if (days.length === 0 || days.length === 7) {
        return 'All days'
    }
    if (days.length === WEEKDAYS.length && WEEKDAYS.every((day) => days.includes(day))) {
        return 'Weekdays'
    }
    if (days.length === 2 && days.includes(6) && days.includes(7)) {
        return 'Weekends'
    }
    return days.map((day) => DAY_LABELS[day]).join(', ')
}
