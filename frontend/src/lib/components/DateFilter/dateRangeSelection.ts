import type { DateRangeSelection } from 'lib/components/DateFilter/DateRangePresetsPanel'
import type { RelativeRangeUnit } from 'lib/components/DateFilter/RelativeRangeInput'
import { dayjs } from 'lib/dayjs'
import { dateMapping, dateStringToDayJs } from 'lib/utils/dateFilters'

import type { DateRange } from '~/queries/schema/schema-general'

// Only the units the picker's rolling input speaks; everything else (quarters, minutes,
// seconds, Start/End anchors) resolves to a concrete custom range below.
const ROLLING_DATE_FROM = /^-(\d+)([hdwmy])$/
const UNIT_BY_LETTER: Record<string, RelativeRangeUnit> = {
    h: 'hours',
    d: 'days',
    w: 'weeks',
    m: 'months',
    y: 'years',
}
const LETTER_BY_UNIT: Record<RelativeRangeUnit, string> = {
    minutes: 'h', // not offered in the picker; mapped defensively
    hours: 'h',
    days: 'd',
    weeks: 'w',
    months: 'm',
    years: 'y',
}

/** PostHog relative-date strings → a picker selection. Named periods resolve through
 *  `dateMapping`, so the picker's chip names and the query vocabulary can't drift. Anything
 *  the picker can't express (quarters, minute ranges, Start/End anchors, relative pairs)
 *  resolves through the canonical parser to a concrete custom range — never a fabricated preset. */
export function selectionForDateRange(dateFrom: string, dateTo: string | null | undefined): DateRangeSelection {
    const rolling = !dateTo && dateFrom.match(ROLLING_DATE_FROM)
    if (rolling) {
        return { kind: 'rolling', count: parseInt(rolling[1], 10), unit: UNIT_BY_LETTER[rolling[2]] }
    }
    const named = dateMapping.find(({ values }) => values[0] === dateFrom && (values[1] ?? null) === (dateTo ?? null))
    if (named) {
        return { kind: 'fixed', name: named.key }
    }
    const start = dateStringToDayJs(dateFrom) ?? (dayjs(dateFrom).isValid() ? dayjs(dateFrom) : null)
    const end = dateTo ? (dateStringToDayJs(dateTo) ?? (dayjs(dateTo).isValid() ? dayjs(dateTo) : null)) : dayjs()
    if (start) {
        return { kind: 'custom', start: start.toDate(), end: (end ?? dayjs()).toDate() }
    }
    return { kind: 'custom', start: dayjs().subtract(7, 'day').toDate(), end: dayjs().toDate() }
}

function formatCustomDate(date: Date, includesTime: boolean): string {
    return dayjs(date).format(includesTime ? 'YYYY-MM-DDTHH:mm:ss' : 'YYYY-MM-DD')
}

export function dateRangeForSelection(selection: DateRangeSelection): Partial<DateRange> {
    if (selection.kind === 'rolling') {
        return { date_from: `-${selection.count}${LETTER_BY_UNIT[selection.unit]}`, date_to: null }
    }
    if (selection.kind === 'fixed') {
        const named = dateMapping.find(({ key }) => key === selection.name)
        return { date_from: named?.values[0] ?? null, date_to: named?.values[1] ?? null }
    }
    // explicitDate is deliberately not written: like the legacy filter, applying a range
    // never touches the "Exact time range" toggle — only the toggle itself does.
    const includesTime = !!selection.includesTime
    return {
        date_from: formatCustomDate(selection.start, includesTime),
        date_to: formatCustomDate(selection.end, includesTime),
    }
}
