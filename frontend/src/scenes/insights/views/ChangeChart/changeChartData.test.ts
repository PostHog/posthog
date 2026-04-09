import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { IndexedTrendResult } from '../../../../trends/types'
import {
    buildChangeChartRows,
    DEFAULT_CHANGE_CHART_VIZ_OPTIONS,
    formatChangeChartPercent,
    getChangeChartBarWidthPercent,
    getChangeChartDomain,
    getChangeChartVizOptions,
    getChangeChartValidationError,
    shouldForceExactDateRangeForChangeChart,
    sortChangeChartRows,
} from './changeChartData'

function makeResult(
    breakdownValue: IndexedTrendResult['breakdown_value'],
    aggregatedValue: number,
    compareLabel: 'current' | 'previous'
): IndexedTrendResult {
    return {
        id: compareLabel === 'current' ? 0 : 1,
        seriesIndex: 0,
        colorIndex: 0,
        action: { id: '$pageview', name: '$pageview', type: 'events', order: 0 },
        label: '$pageview',
        count: aggregatedValue,
        aggregated_value: aggregatedValue,
        data: [],
        days: [],
        labels: [],
        breakdown_value: breakdownValue,
        compare: true,
        compare_label: compareLabel,
    }
}

describe('Change chart utils', () => {
    describe('getChangeChartValidationError', () => {
        const baseBreakdown: BreakdownFilter = { breakdown: '$browser' }

        it.each([
            [
                'rejects non-Trends queries',
                {
                    display: ChartDisplayType.ChangeChart,
                    isTrends: false,
                    series: [{}],
                    breakdownFilter: baseBreakdown,
                    hasFormula: false,
                },
                'Change chart is only available for Trends insights.',
            ],
            [
                'rejects all-time date ranges',
                {
                    display: ChartDisplayType.ChangeChart,
                    isTrends: true,
                    dateRange: { date_from: 'all' },
                    series: [{}],
                    breakdownFilter: baseBreakdown,
                    hasFormula: false,
                },
                'Change chart requires a finite date range and does not support all time.',
            ],
            [
                'rejects multiple series',
                {
                    display: ChartDisplayType.ChangeChart,
                    isTrends: true,
                    series: [{}, {}],
                    breakdownFilter: baseBreakdown,
                    hasFormula: false,
                },
                'Change chart requires exactly one series.',
            ],
            [
                'rejects formulas',
                {
                    display: ChartDisplayType.ChangeChart,
                    isTrends: true,
                    series: [{}],
                    breakdownFilter: baseBreakdown,
                    hasFormula: true,
                },
                'Change chart does not support formulas.',
            ],
            [
                'rejects missing breakdowns',
                {
                    display: ChartDisplayType.ChangeChart,
                    isTrends: true,
                    series: [{}],
                    compareFilter: { compare: true },
                    hasFormula: false,
                },
                'Change chart requires exactly one breakdown.',
            ],
            [
                'rejects missing compare state',
                {
                    display: ChartDisplayType.ChangeChart,
                    isTrends: true,
                    dateRange: { date_from: '-7d' },
                    series: [{ kind: NodeKind.EventsNode }],
                    breakdownFilter: baseBreakdown,
                    compareFilter: { compare: false },
                    hasFormula: false,
                },
                'Change chart requires comparison with the previous period.',
            ],
            [
                'accepts a valid change chart query',
                {
                    display: ChartDisplayType.ChangeChart,
                    isTrends: true,
                    dateRange: { date_from: '-7d' },
                    series: [{ kind: NodeKind.EventsNode }],
                    breakdownFilter: baseBreakdown,
                    compareFilter: { compare: true },
                    hasFormula: false,
                },
                null,
            ],
        ])('%s', (_name, input, expected) => {
            expect(getChangeChartValidationError(input)).toBe(expected)
        })
    })

    describe('buildChangeChartRows', () => {
        it('pairs rows by breakdown and computes change metadata', () => {
            const rows = buildChangeChartRows([
                makeResult('New York', 100, 'current'),
                makeResult('New York', 90, 'previous'),
                makeResult('Los Angeles', 40, 'current'),
                makeResult('Los Angeles', 100, 'previous'),
                makeResult('Chicago', 20, 'current'),
                makeResult('Chicago', 0, 'previous'),
                makeResult('Miami', 30, 'previous'),
                makeResult('Austin', 5, 'current'),
            ])

            expect(rows.map((row) => row.breakdownValue)).toEqual([
                'New York',
                'Los Angeles',
                'Chicago',
                'Miami',
                'Austin',
            ])

            expect(rows[2]).toMatchObject({
                breakdownValue: 'Chicago',
                currentValue: 20,
                previousValue: 0,
                absoluteChange: 20,
                percentChange: Number.POSITIVE_INFINITY,
                direction: 'up',
            })
            expect(rows[4]).toMatchObject({
                breakdownValue: 'Austin',
                currentValue: 5,
                previousValue: 0,
                absoluteChange: 5,
                percentChange: Number.POSITIVE_INFINITY,
                direction: 'up',
            })
            expect(rows[0]).toMatchObject({
                breakdownValue: 'New York',
                currentValue: 100,
                previousValue: 90,
                absoluteChange: 10,
                direction: 'up',
            })
            expect(rows[0].percentChange).toBeCloseTo(11.111, 3)
            expect(rows[1]).toMatchObject({
                breakdownValue: 'Los Angeles',
                currentValue: 40,
                previousValue: 100,
                absoluteChange: -60,
                percentChange: -60,
                direction: 'down',
            })
            expect(rows[3]).toMatchObject({
                breakdownValue: 'Miami',
                currentValue: 0,
                previousValue: 30,
                absoluteChange: -30,
                percentChange: -100,
                direction: 'down',
            })
        })

        it('falls back to count when aggregated values are missing or invalid', () => {
            const rows = buildChangeChartRows([
                {
                    ...makeResult('US', 53, 'current'),
                    aggregated_value: undefined as unknown as number,
                    count: 53,
                },
                {
                    ...makeResult('US', 47, 'previous'),
                    aggregated_value: Number.NaN,
                    count: 47,
                },
            ])

            expect(rows).toHaveLength(1)
            expect(rows[0]).toMatchObject({
                breakdownValue: 'US',
                currentValue: 53,
                previousValue: 47,
                absoluteChange: 6,
                direction: 'up',
            })
            expect(rows[0].percentChange).toBeCloseTo(12.766, 3)
        })
    })

    it('sorts change chart rows using display mode and configured ordering', () => {
        const rows = buildChangeChartRows([
            makeResult('Chicago', 20, 'current'),
            makeResult('Chicago', 0, 'previous'),
            makeResult('New York', 100, 'current'),
            makeResult('New York', 90, 'previous'),
            makeResult('Los Angeles', 40, 'current'),
            makeResult('Los Angeles', 100, 'previous'),
            makeResult('Austin', 5, 'current'),
        ])

        const relativeRows = sortChangeChartRows(rows, DEFAULT_CHANGE_CHART_VIZ_OPTIONS, (row) =>
            String(row.breakdownValue)
        )
        expect(relativeRows.map((row) => row.breakdownValue)).toEqual(['Chicago', 'Austin', 'New York', 'Los Angeles'])

        const absoluteRows = sortChangeChartRows(
            rows,
            { displayMode: 'absolute', orderBy: 'change', orderDirection: 'asc' },
            (row) => String(row.breakdownValue)
        )
        expect(absoluteRows.map((row) => row.breakdownValue)).toEqual(['Los Angeles', 'Austin', 'New York', 'Chicago'])

        const nameRows = sortChangeChartRows(
            rows,
            { displayMode: 'relative', orderBy: 'name', orderDirection: 'asc' },
            (row) => String(row.breakdownValue)
        )
        expect(nameRows.map((row) => row.breakdownValue)).toEqual(['Austin', 'Chicago', 'Los Angeles', 'New York'])
    })

    it('computes change domains and bar widths from finite values while capping infinities', () => {
        const rows = buildChangeChartRows([
            makeResult('Chicago', 20, 'current'),
            makeResult('Chicago', 0, 'previous'),
            makeResult('New York', 100, 'current'),
            makeResult('New York', 90, 'previous'),
            makeResult('Los Angeles', 40, 'current'),
            makeResult('Los Angeles', 100, 'previous'),
        ])

        const percentDomain = getChangeChartDomain(rows, 'relative')
        const absoluteDomain = getChangeChartDomain(rows, 'absolute')

        expect(percentDomain).toBe(60)
        expect(absoluteDomain).toBe(60)
        expect(getChangeChartBarWidthPercent(rows[0], percentDomain, 'relative')).toBe(50)
        expect(getChangeChartBarWidthPercent(rows[1], percentDomain, 'relative')).toBeCloseTo(9.259, 3)
        expect(getChangeChartBarWidthPercent(rows[2], percentDomain, 'relative')).toBe(50)
        expect(getChangeChartBarWidthPercent(rows[1], absoluteDomain, 'absolute')).toBeCloseTo(8.333, 3)
    })

    it('merges change chart viz options with defaults', () => {
        expect(getChangeChartVizOptions(undefined)).toEqual(DEFAULT_CHANGE_CHART_VIZ_OPTIONS)
        expect(
            getChangeChartVizOptions({
                [ChartDisplayType.ChangeChart]: {
                    displayMode: 'absolute',
                    showCurrentValue: false,
                },
            })
        ).toEqual({
            ...DEFAULT_CHANGE_CHART_VIZ_OPTIONS,
            displayMode: 'absolute',
            showCurrentValue: false,
        })
    })

    it.each([
        [null, 'No previous data'],
        [Number.NaN, 'No previous data'],
        [Number.POSITIVE_INFINITY, 'New'],
        [35, '+35%'],
        [-10.5, '-10.5%'],
        [0, '0%'],
    ])('formats percent labels for %s', (value, expected) => {
        expect(formatChangeChartPercent(value)).toBe(expected)
    })

    it.each([
        [{ date_from: '-24h' }, true],
        [{ date_from: '-15m' }, true],
        [{ date_from: '-7d' }, false],
        [{ date_from: '-7d', explicitDate: true }, true],
        [{ date_from: '2026-03-31', explicitDate: false }, false],
    ])('forces exact date ranges for %j -> %s', (dateRange, expected) => {
        expect(shouldForceExactDateRangeForChangeChart(dateRange)).toBe(expected)
    })
})
