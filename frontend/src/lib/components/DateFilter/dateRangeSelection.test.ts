import { dateRangeForSelection, selectionForDateRange } from './dateRangeSelection'

describe('date range selection mapping', () => {
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

    // Strings the picker can't express must resolve to concrete custom ranges via the
    // canonical parser — never be mislabeled as a fabricated preset like "Last 7 days".
    it.each([
        ['-2q', null], // quarters, emitted by the classic rolling filter
        ['-30M', null], // uppercase-M minutes, the interval=second default
        ['-2mStart', null], // Start-anchored string not present in dateMapping
        ['-30d', '-7d'], // relative pair defeats the rolling guard
    ] as const)('resolves unrepresentable %s / %s to a custom range', (dateFrom, dateTo) => {
        const selection = selectionForDateRange(dateFrom, dateTo)
        expect(selection.kind).toBe('custom')
        const custom = selection as Extract<typeof selection, { kind: 'custom' }>
        expect(custom.start.getTime()).toBeLessThan(custom.end.getTime())
    })

    it('quarters resolve to roughly the right span, not a 7-day fabrication', () => {
        const selection = selectionForDateRange('-2q', null)
        expect(selection.kind).toBe('custom')
        const custom = selection as Extract<typeof selection, { kind: 'custom' }>
        const days = (custom.end.getTime() - custom.start.getTime()) / 86_400_000
        expect(days).toBeGreaterThan(170)
        expect(days).toBeLessThan(190)
    })

    it('maps concrete dates to a custom selection and keeps date-only serialization without time', () => {
        const selection = selectionForDateRange('2026-07-01', '2026-07-10')
        expect(selection.kind).toBe('custom')
        expect(dateRangeForSelection(selection)).toEqual({
            date_from: '2026-07-01',
            date_to: '2026-07-10',
        })
    })

    it('serializes times without touching explicitDate when the selection includes time', () => {
        const selection = {
            kind: 'custom' as const,
            start: new Date(2026, 6, 1, 9, 30),
            end: new Date(2026, 6, 1, 17, 0),
            includesTime: true,
        }
        expect(dateRangeForSelection(selection)).toEqual({
            date_from: '2026-07-01T09:30:00',
            date_to: '2026-07-01T17:00:00',
        })
    })

    it('falls back to a concrete last-7-days custom range for unparseable input', () => {
        const selection = selectionForDateRange('garbage', null)
        expect(selection.kind).toBe('custom')
        const custom = selection as Extract<typeof selection, { kind: 'custom' }>
        const days = (custom.end.getTime() - custom.start.getTime()) / 86_400_000
        expect(days).toBeCloseTo(7, 0)
    })
})
