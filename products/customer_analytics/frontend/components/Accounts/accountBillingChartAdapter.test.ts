import { AxisSeriesSettings } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    type BillingChartProps,
    type BillingYSeries,
    MAX_BILLING_SERIES,
    buildBillingSeries,
    canRenderBillingBarChart,
    canRenderBillingComboChart,
    capBillingSeries,
    formatBillingValue,
} from './accountBillingChartAdapter'

const ySeries = (name: string, data: (number | null)[], settings?: AxisSeriesSettings): BillingYSeries => ({
    column: { name, type: { name: 'FLOAT', isNumerical: true }, label: name, dataIndex: 1 },
    data,
    settings,
})

const props = (overrides: Partial<BillingChartProps>): BillingChartProps => ({
    xData: null,
    yData: [],
    visualizationType: ChartDisplayType.ActionsLineGraph,
    chartSettings: {} as ChartSettings,
    ...overrides,
})

describe('accountBillingChartAdapter', () => {
    describe('renderer dispatch', () => {
        const bar = ySeries('bars', [1], { display: { displayType: 'bar' } } as AxisSeriesSettings)
        const line = ySeries('lines', [1], { display: { displayType: 'line' } } as AxisSeriesSettings)
        const rightLine = ySeries('right', [1], {
            display: { displayType: 'line', yAxisPosition: 'right' },
        } as AxisSeriesSettings)
        const plain = ySeries('plain', [1])

        it.each([
            ['mixed bar and line goes to combo', props({ yData: [bar, line] }), true],
            ['single-type series do not', props({ yData: [line, plain] }), false],
            [
                'percent-stacked combo with a left-axis line falls through',
                props({
                    yData: [bar, line],
                    visualizationType: ChartDisplayType.ActionsStackedBar,
                    chartSettings: { stackBars100: true } as ChartSettings,
                }),
                false,
            ],
            [
                'percent-stacked combo is fine when every line is on the right axis',
                props({
                    yData: [bar, rightLine],
                    visualizationType: ChartDisplayType.ActionsStackedBar,
                    chartSettings: { stackBars100: true } as ChartSettings,
                }),
                true,
            ],
        ])('%s', (_name, chartProps, expected) => {
            expect(canRenderBillingComboChart(chartProps)).toBe(expected)
        })

        it.each([
            [
                'a bar chart of plain columns',
                props({ yData: [plain], visualizationType: ChartDisplayType.ActionsBar }),
                true,
            ],
            [
                'a bar chart whose columns are all overridden to line',
                props({ yData: [line], visualizationType: ChartDisplayType.ActionsBar }),
                false,
            ],
            ['a line chart', props({ yData: [plain] }), false],
        ])('bar renderer handles %s', (_name, chartProps, expected) => {
            expect(canRenderBillingBarChart(chartProps)).toBe(expected)
        })
    })

    describe('buildBillingSeries', () => {
        it('draws a gap rather than a zero for null values', () => {
            const [series] = buildBillingSeries([ySeries('events', [1, null, 3])], ChartDisplayType.ActionsLineGraph)
            expect(series.data[0]).toBe(1)
            expect(series.data[1]).toBeNaN()
            expect(series.data[2]).toBe(3)
        })

        it('fills area series and routes right-axis columns', () => {
            const [area, right] = buildBillingSeries(
                [
                    ySeries('area', [1]),
                    ySeries('right', [1], { display: { yAxisPosition: 'right' } } as AxisSeriesSettings),
                ],
                ChartDisplayType.ActionsAreaGraph
            )
            expect(area.fill).toEqual({ opacity: 0.5 })
            expect(area.yAxisId).toBeUndefined()
            expect(right.yAxisId).toBe('right')
        })

        it('keeps percent columns out of the tooltip total', () => {
            const [percent, count] = buildBillingSeries(
                [
                    ySeries('rate', [1], { formatting: { style: 'percent' } } as AxisSeriesSettings),
                    ySeries('count', [1]),
                ],
                ChartDisplayType.ActionsLineGraph
            )
            expect(percent.visibility?.total).toBe(false)
            expect(count.visibility?.total).toBeUndefined()
        })
    })

    describe('capBillingSeries', () => {
        it('caps an excessive yAxis so a saved insight cannot force unbounded chart work', () => {
            const tooMany = Array.from({ length: MAX_BILLING_SERIES + 5 }, (_, i) => ySeries(`s${i}`, [i]))
            expect(capBillingSeries(tooMany)).toHaveLength(MAX_BILLING_SERIES)
        })

        it('keeps the input reference when under the cap, so memoized consumers stay stable', () => {
            const yData = [ySeries('a', [1])]
            expect(capBillingSeries(yData)).toBe(yData)
        })
    })

    describe('formatBillingValue', () => {
        it.each([
            ['caps an unstyled computed value at 3 decimals', 22.222222222222, undefined, '22.222'],
            [
                'honors an explicit zero decimal count',
                22.7,
                { formatting: { decimalPlaces: 0 } } as AxisSeriesSettings,
                '23',
            ],
        ])('%s', (_name, value, settings, expected) => {
            expect(formatBillingValue(value, settings)).toBe(expected)
        })
    })
})
