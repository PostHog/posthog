import { ChartSettings } from '~/queries/schema/schema-general'

import { AxisSeries } from '../../dataVisualizationLogic'
import { buildScatterConfig, buildScatterSeries } from './sqlScatterGraphAdapter'

const numericColumn = (name: string, dataIndex: number): AxisSeries<number | null>['column'] => ({
    name,
    type: { name: 'INTEGER', isNumerical: true },
    label: name,
    dataIndex,
})

const xData = (data: any[]): AxisSeries<string> => ({
    column: numericColumn('duration', 0),
    data: data as string[],
})

const ySeries = (
    name: string,
    data: (number | null)[],
    settings?: AxisSeries<number | null>['settings']
): AxisSeries<number | null> => ({
    column: numericColumn(name, 1),
    data,
    settings,
})

describe('sqlScatterGraphAdapter', () => {
    describe('buildScatterSeries', () => {
        it('pairs each row with the x column, one series per y column', () => {
            const series = buildScatterSeries(xData([1, 2, 3]), [
                ySeries('revenue', [10, 20, 30]),
                ySeries('refunds', [1, 2, 3]),
            ])

            expect(series.map((s) => s.label)).toEqual(['revenue', 'refunds'])
            expect(series[0].points.map(({ x, y }) => [x, y])).toEqual([
                [1, 10],
                [2, 20],
                [3, 30],
            ])
        })

        it('drops rows missing either coordinate rather than plotting them at zero', () => {
            const series = buildScatterSeries(xData([1, null, 3, 'not a number']), [
                ySeries('revenue', [10, 20, null, 40]),
            ])

            expect(series[0].points.map(({ x, y }) => [x, y])).toEqual([[1, 10]])
        })

        it('reads numeric strings, which is how decimal columns arrive', () => {
            const series = buildScatterSeries(xData(['1.5']), [ySeries('revenue', ['2.5' as any])])

            expect(series[0].points.map(({ x, y }) => [x, y])).toEqual([[1.5, 2.5]])
        })

        it('honors a column display label and color, and leaves color unset otherwise', () => {
            const [labeled, plain] = buildScatterSeries(xData([1]), [
                ySeries('revenue', [10], { display: { label: 'Revenue (USD)', color: '#ff0000' } }),
                ySeries('refunds', [1]),
            ])

            expect(labeled.label).toEqual('Revenue (USD)')
            expect(labeled.color).toEqual('#ff0000')
            expect(plain.color).toBeUndefined()
        })

        it('returns nothing without an x column', () => {
            expect(buildScatterSeries(null, [ySeries('revenue', [10])])).toEqual([])
        })
    })

    describe('buildScatterConfig', () => {
        const build = (chartSettings: ChartSettings): ReturnType<typeof buildScatterConfig> =>
            buildScatterConfig({ xData: xData([1]), yData: [ySeries('revenue', [10])], chartSettings })

        it('floats both axes and labels the x axis from its column by default', () => {
            const config = build({})

            expect(config.xAxis).toMatchObject({ label: 'duration', scaleType: 'linear', startAtZero: false })
            expect(config.yAxis).toMatchObject({ scaleType: 'linear', startAtZero: false })
            expect(config.showBestFit).toBe(false)
        })

        it('applies the scatter and y-axis settings', () => {
            const config = build({
                xAxisLabel: 'Session duration',
                scatter: { xScale: 'logarithmic', xStartAtZero: true, showBestFit: true },
                leftYAxisSettings: { label: 'Revenue', scale: 'logarithmic', startAtZero: true, showGridLines: false },
            })

            expect(config.xAxis).toMatchObject({
                label: 'Session duration',
                scaleType: 'log',
                startAtZero: true,
            })
            expect(config.yAxis).toMatchObject({ label: 'Revenue', scaleType: 'log', startAtZero: true })
            expect(config.showGrid).toBe(false)
            expect(config.showBestFit).toBe(true)
        })

        it('formats y values with the column settings', () => {
            const config = buildScatterConfig({
                xData: xData([1]),
                yData: [ySeries('revenue', [10], { formatting: { style: 'number', prefix: '$' } })],
                chartSettings: {},
            })

            const point = { x: 1, y: 1234.5, meta: { settings: { formatting: { prefix: '$' as const } } } } as any
            expect(config.tooltip?.yFormatter?.(1234.5, point)).toEqual('$1234.5')
            expect(config.yAxis?.tickFormatter?.(1234.5)).toEqual('$1,234.5')
        })
    })
})
