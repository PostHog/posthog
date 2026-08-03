import { subDays, subHours, subMinutes, subMonths, subYears } from 'date-fns'

export type DateTimeRangeName = string

export interface DateTimeRange {
    id: number
    name: DateTimeRangeName
    /** Returns the range's start for a given "now". */
    rangeSetter: (date: Date) => Date
    /** Returns the range's end for a given "now". Defaults to "now" itself. */
    endSetter?: (date: Date) => Date
}

export const CUSTOM_RANGE: DateTimeRange = {
    id: 0,
    name: 'Custom',
    rangeSetter: (date) => date,
}

export const quickRanges: DateTimeRange[] = [
    CUSTOM_RANGE,
    { id: 1, name: 'Last 5 minutes', rangeSetter: (d) => subMinutes(d, 5) },
    { id: 2, name: 'Last 15 minutes', rangeSetter: (d) => subMinutes(d, 15) },
    { id: 3, name: 'Last 30 minutes', rangeSetter: (d) => subMinutes(d, 30) },
    { id: 4, name: 'Last 1 hour', rangeSetter: (d) => subHours(d, 1) },
    { id: 5, name: 'Last 3 hours', rangeSetter: (d) => subHours(d, 3) },
    { id: 6, name: 'Last 6 hours', rangeSetter: (d) => subHours(d, 6) },
    { id: 7, name: 'Last 12 hours', rangeSetter: (d) => subHours(d, 12) },
    { id: 8, name: 'Last 24 hours', rangeSetter: (d) => subDays(d, 1) },
    { id: 9, name: 'Last 2 days', rangeSetter: (d) => subDays(d, 2) },
    { id: 10, name: 'Last 7 days', rangeSetter: (d) => subDays(d, 7) },
    { id: 11, name: 'Last 30 days', rangeSetter: (d) => subDays(d, 30) },
    { id: 12, name: 'Last 90 days', rangeSetter: (d) => subDays(d, 90) },
    { id: 13, name: 'Last 6 months', rangeSetter: (d) => subMonths(d, 6) },
    { id: 14, name: 'Last 1 year', rangeSetter: (d) => subYears(d, 1) },
    { id: 15, name: 'Last 2 years', rangeSetter: (d) => subYears(d, 2) },
]
