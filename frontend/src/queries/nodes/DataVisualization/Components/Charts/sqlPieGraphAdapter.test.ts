import { getSeriesColor } from 'lib/colors'

import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'
import { buildPieSeries, buildPieSlices, canRenderSqlPieGraph, formatPieSliceCount } from './sqlPieGraphAdapter'

const baseProps = (visualizationType: ChartDisplayType): LineGraphProps => ({
    xData: null,
    yData: [],
    visualizationType,
    chartSettings: {},
})

describe('sqlPieGraphAdapter', () => {
    describe('formatPieSliceCount', () => {
        it.each([
            ['appends share of total', 25, 100, undefined, false, '25 (25%)'],
            ['rounds share to one decimal place', 1, 3, undefined, false, '1 (33.3%)'],
            ['omits share when total is zero', 5, 0, undefined, false, '5'],
            [
                'omits share for percent-styled values',
                25,
                100,
                { formatting: { style: 'percent' as const } },
                false,
                '25%',
            ],
            [
                'formats value with settings before appending share',
                1234.5,
                2469,
                { formatting: { style: 'number' as const, decimalPlaces: 0 } },
                false,
                '1,235 (50%)',
            ],
            ['leads with share when displaying as percentage', 25, 100, undefined, true, '25% (25)'],
            ['falls back to the value when total is zero in percentage mode', 5, 0, undefined, true, '5'],
        ])('%s', (_name, value, total, settings, asPercent, expected) => {
            expect(formatPieSliceCount(value, total, settings, asPercent)).toEqual(expected)
        })
    })

    describe('buildPieSlices', () => {
        const xData: AxisSeries<string> = {
            column: {
                name: 'category',
                type: {
                    name: 'STRING',
                    isNumerical: false,
                },
                label: 'category',
                dataIndex: 0,
            },
            data: ['alpha', 'beta', 'alpha'],
        }

        it('aggregates a single y-series by x-axis label', () => {
            const yData: AxisSeries<number | null>[] = [
                {
                    column: {
                        name: 'value',
                        type: {
                            name: 'INTEGER',
                            isNumerical: true,
                        },
                        label: 'value',
                        dataIndex: 1,
                    },
                    data: [2, 3, 5],
                    settings: {},
                },
            ]

            expect(buildPieSlices(xData, yData)).toEqual([
                { label: 'alpha', value: 7, color: getSeriesColor(0) },
                { label: 'beta', value: 3, color: getSeriesColor(1) },
            ])
        })

        it('aggregates breakdown series by series total', () => {
            const yData: AxisBreakdownSeries<number | null>[] = [
                {
                    name: 'first',
                    breakdownValue: 'first',
                    data: [1, 2, null],
                    settings: { display: { color: '#111111' } },
                },
                {
                    name: 'second',
                    breakdownValue: 'second',
                    data: [3, 4, 5],
                    settings: { display: { color: '#222222' } },
                },
            ]

            expect(buildPieSlices(xData, yData)).toEqual([
                { label: 'first', value: 3, color: '#111111' },
                { label: 'second', value: 12, color: '#222222' },
            ])
        })

        it('falls back to one slice per y-series when there is no categorical x-axis', () => {
            const noXAxis: AxisSeries<string> = {
                column: {
                    name: 'None',
                    type: {
                        name: 'STRING',
                        isNumerical: false,
                    },
                    label: 'None',
                    dataIndex: -1,
                },
                data: ['', ''],
            }

            const yData: AxisSeries<number | null>[] = [
                {
                    column: {
                        name: 'apples',
                        type: {
                            name: 'INTEGER',
                            isNumerical: true,
                        },
                        label: 'apples',
                        dataIndex: 0,
                    },
                    data: [1, 2],
                    settings: {},
                },
                {
                    column: {
                        name: 'oranges',
                        type: {
                            name: 'INTEGER',
                            isNumerical: true,
                        },
                        label: 'oranges',
                        dataIndex: 1,
                    },
                    data: [3, 4],
                    settings: {},
                },
            ]

            expect(buildPieSlices(noXAxis, yData)).toEqual([
                { label: 'apples', value: 3, color: getSeriesColor(0) },
                { label: 'oranges', value: 7, color: getSeriesColor(1) },
            ])
        })
    })

    describe('buildPieSeries', () => {
        it('maps each slice to a single-value quill series, pinning the slice color', () => {
            expect(
                buildPieSeries([
                    { label: 'alpha', value: 7, color: '#111111' },
                    { label: 'beta', value: 3, color: '#222222' },
                ])
            ).toEqual([
                { key: 'alpha-0', label: 'alpha', color: '#111111', data: [7] },
                { key: 'beta-1', label: 'beta', color: '#222222', data: [3] },
            ])
        })

        it('returns an empty array when there are no slices', () => {
            expect(buildPieSeries([])).toEqual([])
        })
    })

    describe('canRenderSqlPieGraph', () => {
        it.each([
            [ChartDisplayType.ActionsPie, true],
            [ChartDisplayType.ActionsLineGraph, false],
            [ChartDisplayType.ActionsBar, false],
            [ChartDisplayType.ActionsStackedBar, false],
            [ChartDisplayType.ActionsAreaGraph, false],
        ])('returns %s -> %s', (visualizationType, expected) => {
            expect(canRenderSqlPieGraph(baseProps(visualizationType))).toBe(expected)
        })
    })
})
