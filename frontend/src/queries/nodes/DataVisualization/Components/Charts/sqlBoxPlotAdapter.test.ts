import { BoxPlotSettings } from '~/queries/schema/schema-general'

import { Column } from '../../dataVisualizationLogic'
import { buildSqlBoxPlotModel, getAutoBoxPlotSettings } from './sqlBoxPlotAdapter'

const columns: Column[] = [
    { name: 'bucket', label: 'bucket', dataIndex: 0, type: { name: 'STRING', isNumerical: false } },
    { name: 'series', label: 'series', dataIndex: 1, type: { name: 'STRING', isNumerical: false } },
    { name: 'min', label: 'min', dataIndex: 2, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'p25', label: 'p25', dataIndex: 3, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'median', label: 'median', dataIndex: 4, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'mean', label: 'mean', dataIndex: 5, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'p75', label: 'p75', dataIndex: 6, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'max', label: 'max', dataIndex: 7, type: { name: 'FLOAT', isNumerical: true } },
]

const settings: BoxPlotSettings = {
    xAxisColumn: 'bucket',
    seriesColumn: 'series',
    minColumn: 'min',
    p25Column: 'p25',
    medianColumn: 'median',
    meanColumn: 'mean',
    p75Column: 'p75',
    maxColumn: 'max',
}

describe('sqlBoxPlotAdapter', () => {
    test('builds grouped series and leaves missing combinations empty', () => {
        const model = buildSqlBoxPlotModel(
            [
                ['Mon', 'Free', 1, 2, 3, 4, 5, 6],
                ['Tue', 'Paid', 10, 20, 30, 40, 50, 60],
                ['Mon', 'Paid', 7, 8, 9, 10, 11, 12],
            ],
            columns,
            settings
        )

        expect(model.error).toBeNull()
        expect(model.labels).toEqual(['Mon', 'Tue'])
        expect(model.series).toEqual([
            {
                key: 'Free',
                label: 'Free',
                data: [{ min: 1, p25: 2, median: 3, mean: 4, p75: 5, max: 6 }, null],
            },
            {
                key: 'Paid',
                label: 'Paid',
                data: [
                    { min: 7, p25: 8, median: 9, mean: 10, p75: 11, max: 12 },
                    { min: 10, p25: 20, median: 30, mean: 40, p75: 50, max: 60 },
                ],
            },
        ])
    })

    test.each([
        {
            name: 'missing mappings',
            rows: [['Mon', 'Free', 1, 2, 3, 4, 5, 6]],
            boxPlotSettings: { ...settings, medianColumn: undefined },
            error: 'Select a column for Median.',
        },
        {
            name: 'duplicate bucket and series pairs',
            rows: [
                ['Mon', 'Free', 1, 2, 3, 4, 5, 6],
                ['Mon', 'Free', 1, 2, 3, 4, 5, 6],
            ],
            boxPlotSettings: settings,
            error: 'Rows 1 and 2 use the same X-axis and series values. Return one row for each box.',
        },
        {
            name: 'several rows without an x-axis or series',
            rows: [
                ['Mon', 'Free', 1, 2, 3, 4, 5, 6],
                ['Tue', 'Free', 1, 2, 3, 4, 5, 6],
            ],
            boxPlotSettings: { ...settings, xAxisColumn: undefined, seriesColumn: undefined },
            error: 'Select an X-axis column when the query returns more than one row.',
        },
        {
            name: 'different x-axis values with the same display label',
            rows: [
                [null, 'Free', 1, 2, 3, 4, 5, 6],
                ['[No value]', 'Free', 1, 2, 3, 4, 5, 6],
            ],
            boxPlotSettings: settings,
            error: 'Row 2 has an X-axis value that displays as "[No value]", but another value uses the same label. Cast them to distinct strings in SQL.',
        },
        {
            name: 'different series values with the same display label',
            rows: [
                ['Mon', null, 1, 2, 3, 4, 5, 6],
                ['Mon', '[No value]', 1, 2, 3, 4, 5, 6],
            ],
            boxPlotSettings: settings,
            error: 'Row 2 has a series value that displays as "[No value]", but another value uses the same label. Cast them to distinct strings in SQL.',
        },
    ])('reports $name', ({ rows, boxPlotSettings, error }) => {
        expect(buildSqlBoxPlotModel(rows, columns, boxPlotSettings).error).toBe(error)
    })

    test.each([
        {
            name: 'missing statistic',
            invalidRow: ['Mon', 'Free', 1, null, 3, 4, 5, 6],
            skippedRows: { missingStatistic: 1, invalidOrder: 0, meanOutsideRange: 0 },
        },
        {
            name: 'invalid statistic order',
            invalidRow: ['Mon', 'Free', 1, 4, 3, 3, 5, 6],
            skippedRows: { missingStatistic: 0, invalidOrder: 1, meanOutsideRange: 0 },
        },
        {
            name: 'mean outside range',
            invalidRow: ['Mon', 'Free', 1, 2, 3, 9, 5, 6],
            skippedRows: { missingStatistic: 0, invalidOrder: 0, meanOutsideRange: 1 },
        },
    ])('skips a box with $name without hiding valid boxes', ({ invalidRow, skippedRows }) => {
        const model = buildSqlBoxPlotModel([invalidRow, ['Tue', 'Free', 1, 2, 3, 4, 5, 6]], columns, settings)

        expect(model.error).toBeNull()
        expect(model.labels).toEqual(['Tue'])
        expect(model.series).toEqual([
            {
                key: 'Free',
                label: 'Free',
                data: [{ min: 1, p25: 2, median: 3, mean: 4, p75: 5, max: 6 }],
            },
        ])
        expect(model.skippedRows).toEqual(skippedRows)
    })

    test('rejects result shapes that would create a large sparse matrix', () => {
        const rows = Array.from({ length: 101 }, (_, label) =>
            Array.from({ length: 100 }, (_, series) => [label, series, 1, 2, 3, 4, 5, 6])
        ).flat()

        expect(buildSqlBoxPlotModel(rows, columns, settings).error).toBe(
            'The box plot has too many X-axis and series combinations. Reduce the query result.'
        )
    })

    test('rejects more series than the series limit even when the cell matrix stays small', () => {
        const rows = Array.from({ length: 201 }, (_, series) => ['Mon', series, 1, 2, 3, 4, 5, 6])

        expect(buildSqlBoxPlotModel(rows, columns, settings).error).toBe(
            'The box plot has too many series. Reduce the number of distinct series values in the query result.'
        )
    })

    test('uses one distribution when the query returns one row without grouping columns', () => {
        const model = buildSqlBoxPlotModel(
            [[1, 2, 3, 4, 5, 6]],
            columns.slice(2).map((column, dataIndex) => ({ ...column, dataIndex })),
            {
                minColumn: 'min',
                p25Column: 'p25',
                medianColumn: 'median',
                meanColumn: 'mean',
                p75Column: 'p75',
                maxColumn: 'max',
            }
        )

        expect(model.labels).toEqual(['Distribution'])
        expect(model.series).toEqual([
            {
                key: 'Distribution',
                label: 'Distribution',
                data: [{ min: 1, p25: 2, median: 3, mean: 4, p75: 5, max: 6 }],
            },
        ])
    })

    test('groups by series when the query returns one row per series without an x-axis', () => {
        const model = buildSqlBoxPlotModel(
            [
                ['Mon', 'Free', 1, 2, 3, 4, 5, 6],
                ['Mon', 'Paid', 7, 8, 9, 10, 11, 12],
            ],
            columns,
            { ...settings, xAxisColumn: undefined }
        )

        expect(model.error).toBeNull()
        expect(model.labels).toEqual(['Distribution'])
        expect(model.series).toEqual([
            {
                key: 'Free',
                label: 'Free',
                data: [{ min: 1, p25: 2, median: 3, mean: 4, p75: 5, max: 6 }],
            },
            {
                key: 'Paid',
                label: 'Paid',
                data: [{ min: 7, p25: 8, median: 9, mean: 10, p75: 11, max: 12 }],
            },
        ])
    })

    test.each([
        { excludeOutliers: true, expectedMin: -4, expectedMax: 12 },
        { excludeOutliers: false, expectedMin: -100, expectedMax: 100 },
    ])(
        'sets whiskers to $expectedMin and $expectedMax when excludeOutliers is $excludeOutliers',
        ({ excludeOutliers, expectedMin, expectedMax }) => {
            const model = buildSqlBoxPlotModel([['Mon', 'Free', -100, 2, 3, 4, 6, 100]], columns, {
                ...settings,
                excludeOutliers,
            })

            expect(model.series[0].data[0]).toEqual({
                min: expectedMin,
                p25: 2,
                median: 3,
                mean: 4,
                p75: 6,
                max: expectedMax,
            })
        }
    )

    test.each([
        {
            name: 'valid choices',
            current: { xAxisColumn: 'bucket', meanColumn: 'median' },
            expectedGrouping: { xAxisColumn: 'bucket', seriesColumn: 'series' },
            expectedMean: 'median',
        },
        {
            name: 'explicit ungrouped choices',
            current: { xAxisColumn: null, seriesColumn: null },
            expectedGrouping: { xAxisColumn: null, seriesColumn: null },
            expectedMean: 'mean',
        },
    ])('auto-maps conventional aliases and preserves $name', ({ current, expectedGrouping, expectedMean }) => {
        expect(getAutoBoxPlotSettings(columns, current)).toEqual({
            ...expectedGrouping,
            minColumn: 'min',
            p25Column: 'p25',
            medianColumn: 'median',
            meanColumn: expectedMean,
            p75Column: 'p75',
            maxColumn: 'max',
        })
    })
})
