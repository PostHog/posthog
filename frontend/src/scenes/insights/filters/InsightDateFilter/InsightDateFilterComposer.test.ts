import { dateRangeForSelection, selectionForDateRange } from './InsightDateFilterComposer'

describe('InsightDateFilterComposer date range mapping', () => {
    // Persisted PostHog strings must round-trip exactly — a drift here rewrites saved queries.
    it.each([
        ['-7d', null, { kind: 'rolling', count: 7, unit: 'days' }],
        ['-24h', null, { kind: 'rolling', count: 24, unit: 'hours' }],
        ['-1w', null, { kind: 'rolling', count: 1, unit: 'weeks' }],
        ['-1m', null, { kind: 'rolling', count: 1, unit: 'months' }],
        ['-1y', null, { kind: 'rolling', count: 1, unit: 'years' }],
        ['dStart', null, { kind: 'fixed', name: 'Today' }],
        ['-1dStart', '-1dEnd', { kind: 'fixed', name: 'Yesterday' }],
        ['-1mStart', '-1mEnd', { kind: 'fixed', name: 'Last month' }],
        ['wStart', null, { kind: 'fixed', name: 'This week' }],
        ['mStart', null, { kind: 'fixed', name: 'This month' }],
        ['yStart', null, { kind: 'fixed', name: 'Year to date' }],
        ['all', null, { kind: 'fixed', name: 'All time' }],
    ] as const)('round-trips %s / %s', (dateFrom, dateTo, expected) => {
        const selection = selectionForDateRange(dateFrom, dateTo)
        expect(selection).toEqual(expected)
        expect(dateRangeForSelection(selection)).toEqual({ date_from: dateFrom, date_to: dateTo })
    })

    it('maps concrete dates to a custom selection and formats day-granular dates without time', () => {
        const selection = selectionForDateRange('2026-07-01', '2026-07-10')
        expect(selection.kind).toBe('custom')
        expect(dateRangeForSelection(selection)).toEqual({ date_from: '2026-07-01', date_to: '2026-07-10' })
    })

    it('keeps the time component when a custom date has one', () => {
        const selection = selectionForDateRange('2026-07-01T09:30:00', '2026-07-01T17:00:00')
        expect(dateRangeForSelection(selection)).toEqual({
            date_from: '2026-07-01T09:30:00',
            date_to: '2026-07-01T17:00:00',
        })
    })

    it('falls back to last 7 days for unparseable input', () => {
        expect(selectionForDateRange('garbage', null)).toEqual({ kind: 'rolling', count: 7, unit: 'days' })
    })
})
