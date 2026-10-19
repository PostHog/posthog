import { getBIChartDateAxis, getBIChartYearGroups } from './biChartDateAxis'

describe('BI date axis', () => {
    it.each([
        ['America/Los_Angeles', ['2025-12-01', '2026-01-01'], [2025, 2026]],
        ['UTC', ['2025-10-01', '2026-01-01', '2026-04-01'], [2025, 2026]],
        ['America/Los_Angeles', ['2025-12-31T23:00:00Z', '2026-01-01T09:00:00Z'], [2025, 2026]],
        ['UTC', ['2026-04-01', '2026-01-01', '2025-10-01'], [2026, 2025]],
    ])('groups every visible year in %s, including partial years', (timezone, labels, years) => {
        const groups = getBIChartYearGroups(labels, timezone)
        expect(groups.map((group) => group.year)).toEqual(years)
        expect(groups[0].first).toBe(labels[0])
        expect(groups[groups.length - 1].last).toBe(labels[labels.length - 1])
    })

    it('keeps January among the month ticks when years have their own row', () => {
        const labels = ['2025-10-01', '2026-01-01', '2026-04-01']
        const { tickFormatter } = getBIChartDateAxis(labels, 'UTC', 'month')
        expect(labels.map((label, index) => tickFormatter?.(label, index))).toEqual(['October', 'January', 'April'])
    })
})
