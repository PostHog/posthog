import { Column } from '../../../dataVisualizationLogic'
import {
    SCATTER_MAX_POINTS,
    SCATTER_MAX_SERIES,
    SCATTER_OTHER_SERIES_LABEL,
    buildScatterChartData,
} from './scatterChartAdapter'

const column = (name: string, typeName: Column['type']['name'], dataIndex: number, isNumerical = false): Column => ({
    name,
    type: { name: typeName, isNumerical },
    label: name,
    dataIndex,
})

const timestampColumn = column('timestamp', 'DATETIME', 0)
const durationColumn = column('duration', 'FLOAT', 1, true)
const scanTypeColumn = column('scan_type', 'STRING', 2)
const columns = [timestampColumn, durationColumn, scanTypeColumn]

describe('buildScatterChartData', () => {
    it('groups rows into one series per color-by value, keeping the row index on each point', () => {
        const data = buildScatterChartData(
            [
                ['2026-07-17 10:00:00', 1.5, 'single'],
                ['2026-07-17 11:00:00', 2.5, 'two-arm'],
                ['2026-07-17 12:00:00', 3.5, 'single'],
            ],
            columns,
            { xAxisColumn: 'timestamp', yAxisColumn: 'duration', colorByColumn: 'scan_type' }
        )

        expect(data?.xIsDate).toBe(true)
        expect(data?.series.map((series) => [series.label, series.points.length])).toEqual([
            ['single', 2],
            ['two-arm', 1],
        ])
        expect(data?.series[0].points.map((point) => point.rowIndex)).toEqual([0, 2])
        expect(data?.series[0].points[0].x).toEqual(new Date('2026-07-17T10:00:00').valueOf())
    })

    test.each([
        {
            name: 'rows with null or non-numeric values',
            settings: { xAxisColumn: 'timestamp', yAxisColumn: 'duration' },
            rows: [
                ['2026-07-17 10:00:00', 1.5, 'a'],
                [null, 2.5, 'a'],
                ['2026-07-17 11:00:00', null, 'a'],
                ['not a date', 3.5, 'a'],
            ],
            expectedYs: [1.5],
            expectedHidden: 3,
        },
        {
            name: 'non-finite and non-scalar y values',
            settings: { xAxisColumn: 'timestamp', yAxisColumn: 'duration' },
            rows: [
                ['2026-07-17 10:00:00', 'Infinity', 'a'],
                ['2026-07-17 11:00:00', [5], 'a'],
                ['2026-07-17 12:00:00', true, 'a'],
                ['2026-07-17 13:00:00', 4, 'a'],
            ],
            expectedYs: [4],
            expectedHidden: 3,
        },
        {
            name: 'non-positive y values on a log scale',
            settings: { xAxisColumn: 'timestamp', yAxisColumn: 'duration', yAxisScale: 'logarithmic' as const },
            rows: [
                ['2026-07-17 10:00:00', 0, 'a'],
                ['2026-07-17 11:00:00', -1, 'a'],
                ['2026-07-17 12:00:00', 2, 'a'],
            ],
            expectedYs: [2],
            expectedHidden: 2,
        },
    ])('hides $name and reports the count', ({ settings, rows, expectedYs, expectedHidden }) => {
        const data = buildScatterChartData(rows, columns, settings)

        expect(data?.series.flatMap((series) => series.points.map((point) => point.y))).toEqual(expectedYs)
        expect(data?.hiddenPointCount).toEqual(expectedHidden)
    })

    it('folds the smallest color-by groups into an "Other" series beyond the series cap', () => {
        // Two rows for group-0 so it's the largest; one row for each of the other 11 groups.
        const rows = Array.from({ length: SCATTER_MAX_SERIES + 2 }, (_, index) => [
            '2026-07-17 10:00:00',
            index,
            `group-${index}`,
        ])
        rows.push(['2026-07-17 11:00:00', 99, 'group-0'])

        const data = buildScatterChartData(rows, columns, {
            xAxisColumn: 'timestamp',
            yAxisColumn: 'duration',
            colorByColumn: 'scan_type',
        })

        expect(data?.series).toHaveLength(SCATTER_MAX_SERIES)
        expect(data?.series[0].label).toEqual('group-0')
        const otherSeries = data?.series[data.series.length - 1]
        expect(otherSeries?.label).toEqual(SCATTER_OTHER_SERIES_LABEL)
        expect(otherSeries?.points).toHaveLength(3)
    })

    it('caps plotted points and flags truncation', () => {
        const rows = Array.from({ length: SCATTER_MAX_POINTS + 5 }, (_, index) => [index, index, 'a'])
        const numericColumns = [column('x', 'INTEGER', 0, true), column('y', 'INTEGER', 1, true)]

        const data = buildScatterChartData(rows, numericColumns, { xAxisColumn: 'x', yAxisColumn: 'y' })

        expect(data?.truncated).toBe(true)
        expect(data?.series.reduce((count, series) => count + series.points.length, 0)).toEqual(SCATTER_MAX_POINTS)
    })

    it('returns null when the configured columns are not in the result', () => {
        expect(
            buildScatterChartData([['2026-07-17 10:00:00', 1, 'a']], columns, {
                xAxisColumn: 'missing',
                yAxisColumn: 'duration',
            })
        ).toBeNull()
    })
})
