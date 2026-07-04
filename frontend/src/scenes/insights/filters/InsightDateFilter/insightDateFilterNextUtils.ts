import { CUSTOM_RANGE, type DateTimeRange, type DateTimeValue } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { dateFilterToText, startOfWeek } from 'lib/utils/dateFilters'

import { DateRange } from '~/queries/schema/schema-general'

export const DEFAULT_DATE_FROM = '-7d'
const DEFAULT_DATE_LABEL = 'Last 7 days'

export interface InsightDatePreset {
    name: string
    dateFrom: string
    dateTo: string | null
    rangeSetter: (now: Date, weekStartDay: number) => Date
    endSetter?: (now: Date, weekStartDay: number) => Date
}

/** Insight quick ranges: each maps to a PostHog relative date string (so queries stay
 * rolling) plus concrete date setters that preview the range in the quill calendar. */
export const INSIGHT_DATE_PRESETS: InsightDatePreset[] = [
    {
        name: 'Today',
        dateFrom: 'dStart',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).startOf('day').toDate(),
    },
    {
        name: 'Yesterday',
        dateFrom: '-1dStart',
        dateTo: '-1dEnd',
        rangeSetter: (now) => dayjs(now).subtract(1, 'day').startOf('day').toDate(),
        endSetter: (now) => dayjs(now).subtract(1, 'day').endOf('day').toDate(),
    },
    {
        name: 'Last 24 hours',
        dateFrom: '-24h',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).subtract(24, 'hour').toDate(),
    },
    {
        name: 'Last 7 days',
        dateFrom: '-7d',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).subtract(7, 'day').toDate(),
    },
    {
        name: 'Last 14 days',
        dateFrom: '-14d',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).subtract(14, 'day').toDate(),
    },
    {
        name: 'Last 30 days',
        dateFrom: '-30d',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).subtract(30, 'day').toDate(),
    },
    {
        name: 'Last 90 days',
        dateFrom: '-90d',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).subtract(90, 'day').toDate(),
    },
    {
        name: 'Last 180 days',
        dateFrom: '-180d',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).subtract(180, 'day').toDate(),
    },
    {
        name: 'This week',
        dateFrom: 'wStart',
        dateTo: null,
        rangeSetter: (now, weekStartDay) => startOfWeek(dayjs(now), weekStartDay).toDate(),
    },
    {
        name: 'Last week',
        dateFrom: '-1wStart',
        dateTo: '-1wEnd',
        rangeSetter: (now, weekStartDay) => startOfWeek(dayjs(now), weekStartDay).subtract(7, 'day').toDate(),
        endSetter: (now, weekStartDay) =>
            startOfWeek(dayjs(now), weekStartDay).subtract(1, 'day').endOf('day').toDate(),
    },
    {
        name: 'This month',
        dateFrom: 'mStart',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).startOf('month').toDate(),
    },
    {
        name: 'Last month',
        dateFrom: '-1mStart',
        dateTo: '-1mEnd',
        rangeSetter: (now) => dayjs(now).subtract(1, 'month').startOf('month').toDate(),
        endSetter: (now) => dayjs(now).subtract(1, 'month').endOf('month').toDate(),
    },
    {
        name: 'This quarter',
        dateFrom: 'qStart',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).startOf('quarter').toDate(),
    },
    {
        name: 'Last quarter',
        dateFrom: '-1qStart',
        dateTo: '-1qEnd',
        rangeSetter: (now) => dayjs(now).subtract(1, 'quarter').startOf('quarter').toDate(),
        endSetter: (now) => dayjs(now).subtract(1, 'quarter').endOf('quarter').toDate(),
    },
    {
        name: 'Year to date',
        dateFrom: 'yStart',
        dateTo: null,
        rangeSetter: (now) => dayjs(now).startOf('year').toDate(),
    },
]

export function insightDateRanges(weekStartDay: number): DateTimeRange[] {
    return INSIGHT_DATE_PRESETS.map((preset, index) => ({
        id: index + 1,
        name: preset.name,
        rangeSetter: (now: Date) => preset.rangeSetter(now, weekStartDay),
        endSetter: preset.endSetter ? (now: Date) => preset.endSetter!(now, weekStartDay) : undefined,
    }))
}

export function presetForDateStrings(
    dateFrom: string | null | undefined,
    dateTo: string | null | undefined
): InsightDatePreset | undefined {
    return INSIGHT_DATE_PRESETS.find((preset) => preset.dateFrom === dateFrom && preset.dateTo === (dateTo ?? null))
}

export function pickerValueForDateRange(
    dateFrom: string | null | undefined,
    dateTo: string | null | undefined,
    ranges: DateTimeRange[],
    now: Date = new Date()
): DateTimeValue {
    const preset = presetForDateStrings(dateFrom ?? DEFAULT_DATE_FROM, dateTo)
    if (preset) {
        const range = ranges.find((r) => r.name === preset.name)
        if (range) {
            return { start: range.rangeSetter(now), end: range.endSetter?.(now) ?? now, range }
        }
    }
    const parsedFrom = dateFrom ? dayjs(dateFrom) : null
    const parsedTo = dateTo ? dayjs(dateTo) : null
    return {
        start: parsedFrom?.isValid() ? parsedFrom.toDate() : dayjs(now).subtract(7, 'day').toDate(),
        end: parsedTo?.isValid() ? parsedTo.toDate() : now,
        range: CUSTOM_RANGE,
    }
}

export function dateRangeUpdateForPickerValue(value: DateTimeValue): Pick<DateRange, 'date_from' | 'date_to'> {
    if (value.range.id !== CUSTOM_RANGE.id) {
        const preset = INSIGHT_DATE_PRESETS.find((p) => p.name === value.range.name)
        if (preset) {
            return { date_from: preset.dateFrom, date_to: preset.dateTo }
        }
    }
    // Custom ranges commit day-granular browser-local dates; presets stay relative strings the
    // backend resolves in project timezone, so the calendar is a local-time preview by design.
    return {
        date_from: dayjs(value.start).format('YYYY-MM-DD'),
        date_to: dayjs(value.end).format('YYYY-MM-DD'),
    }
}

export function insightDateLabel(dateFrom: string | null | undefined, dateTo: string | null | undefined): string {
    if (!dateFrom) {
        return DEFAULT_DATE_LABEL
    }
    return (
        presetForDateStrings(dateFrom, dateTo)?.name ??
        dateFilterToText(dateFrom, dateTo, DEFAULT_DATE_LABEL) ??
        DEFAULT_DATE_LABEL
    )
}
