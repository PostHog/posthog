import { CUSTOM_RANGE } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import {
    INSIGHT_DATE_PRESETS,
    dateRangeUpdateForPickerValue,
    insightDateLabel,
    insightDateRanges,
    pickerValueForDateRange,
} from './insightDateFilterNextUtils'

// Friday May 15 2026, mid-Q2
const NOW = new Date(2026, 4, 15, 12, 0, 0)

describe('insightDateFilterNextUtils', () => {
    const ranges = insightDateRanges(1)

    test.each(INSIGHT_DATE_PRESETS.map((p) => ({ name: p.name, dateFrom: p.dateFrom, dateTo: p.dateTo })))(
        'round-trips $name through picker value and back to $dateFrom..$dateTo',
        ({ name, dateFrom, dateTo }) => {
            const value = pickerValueForDateRange(dateFrom, dateTo, ranges, NOW)
            expect(value.range.name).toBe(name)
            expect(dateRangeUpdateForPickerValue(value)).toEqual({ date_from: dateFrom, date_to: dateTo })
        }
    )

    test.each([
        { name: 'This quarter', start: '2026-04-01', end: '2026-05-15' },
        { name: 'Last quarter', start: '2026-01-01', end: '2026-03-31' },
        { name: 'Last month', start: '2026-04-01', end: '2026-04-30' },
        { name: 'Year to date', start: '2026-01-01', end: '2026-05-15' },
        { name: 'This week', start: '2026-05-11', end: '2026-05-15' },
        { name: 'Last week', start: '2026-05-04', end: '2026-05-10' },
    ])('$name previews $start..$end in the calendar (week starts Monday)', ({ name, start, end }) => {
        const preset = INSIGHT_DATE_PRESETS.find((p) => p.name === name)!
        const value = pickerValueForDateRange(preset.dateFrom, preset.dateTo, ranges, NOW)
        expect(dayjs(value.start).format('YYYY-MM-DD')).toBe(start)
        expect(dayjs(value.end).format('YYYY-MM-DD')).toBe(end)
    })

    it('starts weeks on Sunday when the team week starts on Sunday', () => {
        const sundayRanges = insightDateRanges(0)
        const value = pickerValueForDateRange('wStart', null, sundayRanges, NOW)
        expect(dayjs(value.start).format('YYYY-MM-DD')).toBe('2026-05-10')
    })

    it('maps a custom calendar selection to absolute day-granular dates', () => {
        const update = dateRangeUpdateForPickerValue({
            start: new Date(2026, 2, 3),
            end: new Date(2026, 2, 20, 23, 59, 59),
            range: CUSTOM_RANGE,
        })
        expect(update).toEqual({ date_from: '2026-03-03', date_to: '2026-03-20' })
    })

    it('falls back to a custom picker value for absolute date strings', () => {
        const value = pickerValueForDateRange('2026-03-03', '2026-03-20', ranges, NOW)
        expect(value.range).toBe(CUSTOM_RANGE)
        expect(dayjs(value.start).format('YYYY-MM-DD')).toBe('2026-03-03')
        expect(dayjs(value.end).format('YYYY-MM-DD')).toBe('2026-03-20')
    })

    test.each([
        { dateFrom: 'qStart', dateTo: null, expected: 'This quarter' },
        { dateFrom: '-1qStart', dateTo: '-1qEnd', expected: 'Last quarter' },
        { dateFrom: '-3w', dateTo: null, expected: 'Last 3 weeks' },
        { dateFrom: 'all', dateTo: null, expected: 'All time' },
        { dateFrom: null, dateTo: null, expected: 'Last 7 days' },
    ])('labels $dateFrom..$dateTo as $expected', ({ dateFrom, dateTo, expected }) => {
        expect(insightDateLabel(dateFrom, dateTo)).toBe(expected)
    })
})
