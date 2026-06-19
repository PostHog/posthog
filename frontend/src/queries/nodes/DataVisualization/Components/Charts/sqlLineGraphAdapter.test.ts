import { type TooltipContext, type TrendLineConfig } from '@posthog/quill-charts'

import { ChartSettings, GoalLine } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'
import {
    AREA_FILL_OPACITY,
    MAX_SERIES,
    type SqlLineYSeries,
    barLayoutForDisplay,
    buildBarChartConfig,
    buildComboChartConfig,
    buildLineChartConfig,
    buildSeries,
    buildSqlTooltipConfig,
    buildTrendLineConfigs,
    canRenderSqlBarGraph,
    canRenderSqlComboGraph,
    canRenderSqlLineGraph,
    capYSeriesData,
    comboBarLayoutForDisplay,
    exceedsMaxSeries,
    formatSqlSeriesValue,
    hasMixedSeriesTypes,
    seriesDisplayType,
} from './sqlLineGraphAdapter'

const numericColumn = (name: string, dataIndex: number): AxisSeries<number | null>['column'] => ({
    name,
    type: { name: 'INTEGER', isNumerical: true },
    label: name,
    dataIndex,
})

const ySeries = (
    name: string,
    data: (number | null)[],
    settings: AxisSeries<number | null>['settings'] = {}
): AxisSeries<number | null> => ({ column: numericColumn(name, 1), data, settings })

const breakdownSeries = (
    breakdownValue: string,
    data: (number | null)[],
    settings: AxisBreakdownSeries<number | null>['settings'] = {}
): AxisBreakdownSeries<number | null> => ({ name: breakdownValue, breakdownValue, data, settings })

const baseProps = (overrides: Partial<LineGraphProps>): LineGraphProps => ({
    xData: null,
    yData: [],
    visualizationType: ChartDisplayType.ActionsLineGraph,
    chartSettings: {},
    ...overrides,
})

describe('sqlLineGraphAdapter', () => {
    describe('canRenderSqlLineGraph', () => {
        it.each([
            ['line graph', ChartDisplayType.ActionsLineGraph, true],
            ['area graph', ChartDisplayType.ActionsAreaGraph, true],
            ['bar graph', ChartDisplayType.ActionsBar, false],
            ['stacked bar graph', ChartDisplayType.ActionsStackedBar, false],
        ])('returns %s support correctly for %s', (_name, visualizationType, expected) => {
            expect(canRenderSqlLineGraph(baseProps({ visualizationType }))).toBe(expected)
        })

        it('falls back when any series renders as a bar', () => {
            const yData = [ySeries('a', [1]), ySeries('b', [2], { display: { displayType: 'bar' } })]
            expect(canRenderSqlLineGraph(baseProps({ yData }))).toBe(false)
        })

        it.each([
            ['line graph', ChartDisplayType.ActionsLineGraph],
            ['area graph', ChartDisplayType.ActionsAreaGraph],
        ])('renders trend-line series natively rather than falling back for a %s', (_name, visualizationType) => {
            const yData = [ySeries('a', [1], { display: { trendLine: true } })]
            expect(canRenderSqlLineGraph(baseProps({ visualizationType, yData }))).toBe(true)
        })

        it('renders right y-axis series natively rather than falling back', () => {
            const yData = [ySeries('a', [1]), ySeries('b', [2], { display: { yAxisPosition: 'right' } })]
            expect(canRenderSqlLineGraph(baseProps({ yData }))).toBe(true)
        })
    })

    describe('canRenderSqlBarGraph', () => {
        it.each([
            ['line graph', ChartDisplayType.ActionsLineGraph, false],
            ['area graph', ChartDisplayType.ActionsAreaGraph, false],
            ['bar graph', ChartDisplayType.ActionsBar, true],
            ['stacked bar graph', ChartDisplayType.ActionsStackedBar, true],
        ])('returns %s support correctly for %s', (_name, visualizationType, expected) => {
            expect(canRenderSqlBarGraph(baseProps({ visualizationType }))).toBe(expected)
        })

        it.each([
            ['line', 'line' as const],
            ['area', 'area' as const],
        ])('falls back when any series overrides display to %s (mixed combo chart)', (_name, displayType) => {
            const yData = [ySeries('a', [1]), ySeries('b', [2], { display: { displayType } })]
            expect(canRenderSqlBarGraph(baseProps({ visualizationType: ChartDisplayType.ActionsBar, yData }))).toBe(
                false
            )
        })

        // Trend lines force the legacy fallback on the bar path because quill's
        // TimeSeriesBarChart has no trend-line support — keep this until it does.
        it.each([
            ['a plain series', [ySeries('a', [1], { display: { trendLine: true } })]],
            ['a breakdown series', [breakdownSeries('chrome', [1], { display: { trendLine: true } })]],
        ])('falls back when %s has a trend line', (_name, yData) => {
            expect(canRenderSqlBarGraph(baseProps({ visualizationType: ChartDisplayType.ActionsBar, yData }))).toBe(
                false
            )
        })

        it('falls back when any series targets the right y-axis', () => {
            const yData = [ySeries('a', [1], { display: { yAxisPosition: 'right' } })]
            expect(canRenderSqlBarGraph(baseProps({ visualizationType: ChartDisplayType.ActionsBar, yData }))).toBe(
                false
            )
        })
    })

    describe('seriesDisplayType', () => {
        it.each<[string, ChartDisplayType, AxisSeries<number | null>['settings'], string]>([
            ['bar override wins', ChartDisplayType.ActionsLineGraph, { display: { displayType: 'bar' } }, 'bar'],
            ['line override wins', ChartDisplayType.ActionsBar, { display: { displayType: 'line' } }, 'line'],
            ['area override wins', ChartDisplayType.ActionsBar, { display: { displayType: 'area' } }, 'area'],
            ['auto on a line graph is a line', ChartDisplayType.ActionsLineGraph, {}, 'line'],
            ['auto on an area graph is an area', ChartDisplayType.ActionsAreaGraph, {}, 'area'],
            ['auto on a bar graph is a bar', ChartDisplayType.ActionsBar, {}, 'bar'],
            ['auto on a stacked bar graph is a bar', ChartDisplayType.ActionsStackedBar, {}, 'bar'],
            [
                "the 'auto' display type defers to the chart type",
                ChartDisplayType.ActionsBar,
                { display: { displayType: 'auto' } },
                'bar',
            ],
        ])('derives %s', (_name, visualizationType, settings, expected) => {
            expect(seriesDisplayType(visualizationType, settings)).toBe(expected)
        })
    })

    describe('hasMixedSeriesTypes', () => {
        it.each<[string, ChartDisplayType, AxisSeries<number | null>[], boolean]>([
            [
                'bar + line on a line graph',
                ChartDisplayType.ActionsLineGraph,
                [ySeries('a', [1]), ySeries('b', [2], { display: { displayType: 'bar' } })],
                true,
            ],
            [
                'line + bar on a bar graph',
                ChartDisplayType.ActionsBar,
                [ySeries('a', [1]), ySeries('b', [2], { display: { displayType: 'line' } })],
                true,
            ],
            [
                'bar + area on a stacked bar graph',
                ChartDisplayType.ActionsStackedBar,
                [ySeries('a', [1]), ySeries('b', [2], { display: { displayType: 'area' } })],
                true,
            ],
            [
                'all lines on a line graph',
                ChartDisplayType.ActionsLineGraph,
                [ySeries('a', [1]), ySeries('b', [2])],
                false,
            ],
            ['all bars on a bar graph', ChartDisplayType.ActionsBar, [ySeries('a', [1]), ySeries('b', [2])], false],
            [
                'line + area is line-like, not mixed',
                ChartDisplayType.ActionsLineGraph,
                [ySeries('a', [1]), ySeries('b', [2], { display: { displayType: 'area' } })],
                false,
            ],
        ])('detects %s', (_name, visualizationType, yData, expected) => {
            expect(hasMixedSeriesTypes(yData, visualizationType)).toBe(expected)
        })
    })

    describe('canRenderSqlComboGraph', () => {
        // Explicit line + bar so the mix holds regardless of the base chart type's auto resolution.
        const mixed = [
            ySeries('a', [1], { display: { displayType: 'line' } }),
            ySeries('b', [2], { display: { displayType: 'bar' } }),
        ]

        it.each([
            ['line graph', ChartDisplayType.ActionsLineGraph],
            ['area graph', ChartDisplayType.ActionsAreaGraph],
            ['bar graph', ChartDisplayType.ActionsBar],
            ['stacked bar graph', ChartDisplayType.ActionsStackedBar],
        ])('renders mixed series on a %s', (_name, visualizationType) => {
            expect(canRenderSqlComboGraph(baseProps({ visualizationType, yData: mixed }))).toBe(true)
        })

        it('does not render when series are all one type', () => {
            const yData = [ySeries('a', [1]), ySeries('b', [2])]
            expect(canRenderSqlComboGraph(baseProps({ visualizationType: ChartDisplayType.ActionsBar, yData }))).toBe(
                false
            )
        })

        it('does not claim an unsupported chart type', () => {
            expect(
                canRenderSqlComboGraph(baseProps({ visualizationType: ChartDisplayType.ActionsPie, yData: mixed }))
            ).toBe(false)
        })

        it('falls back when any series has a trend line (no combo trend-line support)', () => {
            const yData = [
                ySeries('a', [1], { display: { displayType: 'bar' } }),
                ySeries('b', [2], { display: { displayType: 'line', trendLine: true } }),
            ]
            expect(canRenderSqlComboGraph(baseProps({ visualizationType: ChartDisplayType.ActionsBar, yData }))).toBe(
                false
            )
        })

        it('falls back for percent-stacked bars (unsupported by ComboChart)', () => {
            expect(
                canRenderSqlComboGraph(
                    baseProps({
                        visualizationType: ChartDisplayType.ActionsStackedBar,
                        yData: mixed,
                        chartSettings: { stackBars100: true },
                    })
                )
            ).toBe(false)
        })

        it('falls back when any series targets the right y-axis', () => {
            const yData = [
                ySeries('a', [1], { display: { displayType: 'bar' } }),
                ySeries('b', [2], { display: { displayType: 'line', yAxisPosition: 'right' } }),
            ]
            expect(canRenderSqlComboGraph(baseProps({ visualizationType: ChartDisplayType.ActionsBar, yData }))).toBe(
                false
            )
        })
    })

    describe('comboBarLayoutForDisplay', () => {
        it.each([
            ['stacked for a stacked bar graph', ChartDisplayType.ActionsStackedBar, 'stacked'],
            ['grouped for a bar graph', ChartDisplayType.ActionsBar, 'grouped'],
            ['grouped for a line graph', ChartDisplayType.ActionsLineGraph, 'grouped'],
        ])('returns %s', (_name, visualizationType, expected) => {
            expect(comboBarLayoutForDisplay(visualizationType)).toBe(expected)
        })
    })

    describe('barLayoutForDisplay', () => {
        it.each([
            ['grouped bars for a bar graph', ChartDisplayType.ActionsBar, {}, 'grouped'],
            ['stacked bars for a stacked bar graph', ChartDisplayType.ActionsStackedBar, {}, 'stacked'],
            [
                'percent bars when stackBars100 is on for a stacked bar graph',
                ChartDisplayType.ActionsStackedBar,
                { stackBars100: true },
                'percent',
            ],
        ])('returns %s', (_name, visualizationType, chartSettings, expected) => {
            expect(barLayoutForDisplay(visualizationType, chartSettings as ChartSettings)).toBe(expected)
        })
    })

    describe('exceedsMaxSeries', () => {
        const tooMany = Array.from({ length: MAX_SERIES + 1 }, (_, i) => ySeries(`s${i}`, [i]))

        it('is true above the cap outside a dashboard', () => {
            expect(exceedsMaxSeries(tooMany, undefined)).toBe(true)
        })

        it('is false above the cap on a dashboard', () => {
            expect(exceedsMaxSeries(tooMany, 'dash-1')).toBe(false)
        })

        it('is false at or below the cap', () => {
            expect(exceedsMaxSeries([ySeries('a', [1])], undefined)).toBe(false)
        })
    })

    describe('capYSeriesData', () => {
        it('returns null for missing data', () => {
            expect(capYSeriesData(undefined as unknown as LineGraphProps['yData'])).toBeNull()
        })

        it('returns the data unchanged at or below the cap', () => {
            const yData = [ySeries('a', [1]), ySeries('b', [2])]
            expect(capYSeriesData(yData)).toBe(yData)
        })

        it('slices to the cap when exceeded', () => {
            const yData = Array.from({ length: MAX_SERIES + 5 }, (_, i) => ySeries(`s${i}`, [i]))
            expect(capYSeriesData(yData)).toHaveLength(MAX_SERIES)
        })
    })

    describe('buildSeries', () => {
        it('maps nulls to NaN so quill draws gaps', () => {
            const [series] = buildSeries([ySeries('a', [1, null, 3])], ChartDisplayType.ActionsLineGraph)
            expect(series.data).toEqual([1, NaN, 3])
        })

        it('only pins an explicit color, leaving palette assignment to quill otherwise', () => {
            const [withColor, withoutColor] = buildSeries(
                [ySeries('a', [1], { display: { color: '#abcdef' } }), ySeries('b', [2])],
                ChartDisplayType.ActionsLineGraph
            )
            expect(withColor.color).toBe('#abcdef')
            expect(withoutColor.color).toBeUndefined()
        })

        it('adds an area fill for area graphs', () => {
            const [series] = buildSeries([ySeries('a', [1])], ChartDisplayType.ActionsAreaGraph)
            expect(series.fill).toEqual({ opacity: AREA_FILL_OPACITY })
        })

        it('adds an area fill when a series opts into area display', () => {
            const [series] = buildSeries(
                [ySeries('a', [1], { display: { displayType: 'area' } })],
                ChartDisplayType.ActionsLineGraph
            )
            expect(series.fill).toEqual({ opacity: AREA_FILL_OPACITY })
        })

        it('omits the fill for plain line graphs', () => {
            const [series] = buildSeries([ySeries('a', [1])], ChartDisplayType.ActionsLineGraph)
            expect(series.fill).toBeUndefined()
        })

        it('omits the area fill for a bar-override series on an area graph', () => {
            const [series] = buildSeries(
                [ySeries('a', [1], { display: { displayType: 'bar' } })],
                ChartDisplayType.ActionsAreaGraph
            )
            expect(series.type).toBe('bar')
            expect(series.fill).toBeUndefined()
        })

        it('keys breakdown series by breakdown value', () => {
            const [series] = buildSeries([breakdownSeries('chrome', [1])], ChartDisplayType.ActionsLineGraph)
            expect(series.key).toBe('chrome')
        })

        it('derives each series quill type from its displayType', () => {
            const [bar, line, area] = buildSeries(
                [
                    ySeries('a', [1], { display: { displayType: 'bar' } }),
                    ySeries('b', [2]),
                    ySeries('c', [3], { display: { displayType: 'area' } }),
                ],
                ChartDisplayType.ActionsLineGraph
            )
            expect([bar.type, line.type, area.type]).toEqual(['bar', 'line', 'area'])
        })

        it.each<[string, AxisSeries<number | null>['settings'], string | undefined]>([
            ['right when the series targets the right axis', { display: { yAxisPosition: 'right' } }, 'right'],
            ['unset when the series targets the left axis', { display: { yAxisPosition: 'left' } }, undefined],
            ['unset when no axis is specified', {}, undefined],
        ])('assigns yAxisId %s', (_name, settings, expected) => {
            const [series] = buildSeries([ySeries('a', [1], settings)], ChartDisplayType.ActionsLineGraph)
            expect(series.yAxisId).toBe(expected)
        })

        it('threads each series settings through meta for the tooltip', () => {
            const usd: AxisSeries<number | null>['settings'] = { formatting: { prefix: '$' } }
            const [withSettings, plain] = buildSeries(
                [ySeries('revenue', [1], usd), ySeries('count', [2])],
                ChartDisplayType.ActionsLineGraph
            )
            expect(withSettings.meta).toEqual({ settings: usd })
            expect(plain.meta).toEqual({ settings: {} })
        })
    })

    describe('buildTrendLineConfigs', () => {
        it.each<[string, SqlLineYSeries[] | null | undefined, TrendLineConfig[]]>([
            [
                'one linear config per opting-in series, keyed by original index',
                [
                    ySeries('a', [1], { display: { trendLine: true } }),
                    ySeries('b', [2]),
                    ySeries('c', [3], { display: { trendLine: true } }),
                ],
                [
                    { seriesKey: 'a-0', kind: 'linear' },
                    { seriesKey: 'c-2', kind: 'linear' },
                ],
            ],
            ['none when no series opts in', [ySeries('a', [1]), ySeries('b', [2])], []],
            ['none for missing data', undefined, []],
            ['none for null data', null, []],
            [
                'breakdown trend lines keyed by breakdown value',
                [breakdownSeries('chrome', [1], { display: { trendLine: true } })],
                [{ seriesKey: 'chrome', kind: 'linear' }],
            ],
        ])('builds %s', (_name, ySeriesData, expected) => {
            expect(buildTrendLineConfigs(ySeriesData)).toEqual(expected)
        })

        it('keys each trend line to the series buildSeries assigns', () => {
            const yData = [
                ySeries('a', [1]),
                ySeries('b', [2], { display: { trendLine: true } }),
                breakdownSeries('chrome', [3], { display: { trendLine: true } }),
            ]
            const seriesKeys = buildSeries(yData, ChartDisplayType.ActionsLineGraph).map((s) => s.key)
            const trendLineKeys = buildTrendLineConfigs(yData).map((t) => t.seriesKey)
            // Both derive from getSeriesKey on the same array, so the trend lines are the opt-in subset.
            expect(seriesKeys).toEqual(['a-0', 'b-1', 'chrome'])
            expect(trendLineKeys).toEqual(['b-1', 'chrome'])
        })

        it('uses array-position indexing, so keys stay aligned with buildSeries however the cap slices', () => {
            const yData = [
                ySeries('a', [1]),
                ySeries('b', [2], { display: { trendLine: true } }),
                ySeries('c', [3]),
                ySeries('d', [4], { display: { trendLine: true } }),
            ]
            const seriesKeys = buildSeries(yData, ChartDisplayType.ActionsLineGraph).map((s) => s.key)
            const trendLineKeys = buildTrendLineConfigs(yData).map((t) => t.seriesKey)
            expect(trendLineKeys).toEqual([seriesKeys[1], seriesKeys[3]])
        })
    })

    describe('formatSqlSeriesValue', () => {
        it('applies the column settings and stringifies the result', () => {
            expect(formatSqlSeriesValue(1200, { formatting: { prefix: '$' } })).toBe('$1200')
        })

        it('falls back to the raw value when formatting yields null', () => {
            expect(formatSqlSeriesValue(NaN)).toBe('NaN')
        })
    })

    describe('buildSqlTooltipConfig', () => {
        const entry = (settings: AxisSeries<number | null>['settings']): TooltipContext['seriesData'][number] => ({
            series: { key: 'r', label: 'Revenue', data: [1200], meta: { settings } },
            value: 1200,
            color: '#000000',
        })

        it('enables a pinnable tooltip', () => {
            const config = buildSqlTooltipConfig({}, [ySeries('a', [1])])
            expect(config.enabled).toBe(true)
            expect(config.pinnable).toBe(true)
        })

        it('formats each row with its own column settings from series.meta', () => {
            const config = buildSqlTooltipConfig({}, [ySeries('a', [1])])
            const format = config.valueFormatter!
            expect(format(1200, entry({ formatting: { prefix: '$' } }))).toBe('$1200')
        })

        it.each([
            ['shows the total row by default', {}, true],
            ['shows the total row when showTotalRow is true', { showTotalRow: true }, true],
            ['hides the total row when showTotalRow is false', { showTotalRow: false }, false],
        ])('%s', (_name, chartSettings, expected) => {
            expect(buildSqlTooltipConfig(chartSettings as ChartSettings, []).showTotal).toBe(expected)
        })

        it('formats the total with the first series settings', () => {
            const config = buildSqlTooltipConfig({}, [ySeries('revenue', [1], { formatting: { prefix: '$' } })])
            const formatTotal = config.totalFormatter!
            expect(formatTotal(5000)).toBe('$5000')
        })
    })

    describe('buildLineChartConfig', () => {
        const dateXData: AxisSeries<string> = {
            column: { name: 'day', type: { name: 'DATE', isNumerical: false }, label: 'day', dataIndex: 0 },
            data: ['2024-01-01', '2024-01-02'],
        }
        const stringXData: AxisSeries<string> = {
            column: { name: 'name', type: { name: 'STRING', isNumerical: false }, label: 'name', dataIndex: 0 },
            data: ['a', 'b'],
        }

        it('adds an x-axis tick formatter for date axes', () => {
            const config = buildLineChartConfig({ xData: dateXData, chartSettings: {}, timezone: 'UTC' })
            expect(config.xAxis?.tickFormatter).toBeInstanceOf(Function)
        })

        it('omits the tick formatter for non-date axes', () => {
            const config = buildLineChartConfig({ xData: stringXData, chartSettings: {}, timezone: 'UTC' })
            expect(config.xAxis?.tickFormatter).toBeUndefined()
        })

        it('maps logarithmic scale and y-axis settings', () => {
            const chartSettings: ChartSettings = {
                leftYAxisSettings: { label: 'Count', scale: 'logarithmic', showGridLines: false, showTicks: false },
            }
            const config = buildLineChartConfig({ xData: dateXData, chartSettings, timezone: 'UTC' })
            expect(config.yAxis).toMatchObject({ label: 'Count', scale: 'log', showGrid: false, hide: true })
        })

        it('defaults to a linear scale with grid shown', () => {
            const config = buildLineChartConfig({ xData: dateXData, chartSettings: {}, timezone: 'UTC' })
            expect(config.yAxis).toMatchObject({ scale: 'linear', showGrid: true })
        })

        it('keeps a single-object yAxis when no series targets the right axis', () => {
            const ySeriesData = [ySeries('a', [1, 2]), ySeries('b', [3, 4])]
            const config = buildLineChartConfig({ xData: dateXData, chartSettings: {}, timezone: 'UTC', ySeriesData })
            expect(Array.isArray(config.yAxis)).toBe(false)
        })

        it('emits a per-axis array honoring each column settings when a series targets the right axis', () => {
            const ySeriesData = [ySeries('a', [1, 2]), ySeries('b', [3, 4], { display: { yAxisPosition: 'right' } })]
            const chartSettings: ChartSettings = {
                leftYAxisSettings: { label: 'Left', scale: 'logarithmic' },
                rightYAxisSettings: { label: 'Right', showGridLines: false },
            }
            const config = buildLineChartConfig({ xData: dateXData, chartSettings, timezone: 'UTC', ySeriesData })
            expect(config.yAxis).toEqual([
                { id: 'left', position: 'left', label: 'Left', scale: 'log', showGrid: true, hide: false },
                { id: 'right', position: 'right', label: 'Right', scale: 'linear', showGrid: false, hide: false },
            ])
        })

        it.each([
            ['shows', true, true],
            ['hides', false, false],
            ['hides by default', undefined, false],
        ])('%s the built-in legend from showLegend', (_name, showLegend, expected) => {
            const config = buildLineChartConfig({ xData: dateXData, chartSettings: { showLegend }, timezone: 'UTC' })
            expect(config.legend).toEqual({ show: expected, position: 'top', interactive: true })
        })

        it('wires goalLines through schemaGoalLinesToConfigs', () => {
            const goalLines: GoalLine[] = [{ label: 'Target', value: 100 }]
            const config = buildLineChartConfig({ xData: dateXData, chartSettings: {}, timezone: 'UTC', goalLines })
            expect(config.goalLines).toHaveLength(1)
            expect(config.goalLines?.[0]).toMatchObject({ value: 100, label: 'Target' })
        })

        it.each<[string, SqlLineYSeries[], TrendLineConfig[]]>([
            [
                'wires trend lines from series that opt in, keyed to match buildSeries',
                [ySeries('a', [1, 2], { display: { trendLine: true } }), ySeries('b', [3, 4])],
                [{ seriesKey: 'a-0', kind: 'linear' }],
            ],
            ['omits trend lines when no series opts in', [ySeries('a', [1, 2]), ySeries('b', [3, 4])], []],
        ])('%s', (_name, ySeriesData, expected) => {
            const config = buildLineChartConfig({ xData: dateXData, chartSettings: {}, timezone: 'UTC', ySeriesData })
            expect(config.trendLines).toEqual(expected)
        })
    })

    describe('buildBarChartConfig', () => {
        const dateXData: AxisSeries<string> = {
            column: { name: 'day', type: { name: 'DATE', isNumerical: false }, label: 'day', dataIndex: 0 },
            data: ['2024-01-01', '2024-01-02'],
        }

        it('forces a linear y-axis scale for percent-stacked bars', () => {
            const chartSettings: ChartSettings = {
                stackBars100: true,
                leftYAxisSettings: { scale: 'logarithmic' },
            }
            const config = buildBarChartConfig({
                xData: dateXData,
                chartSettings,
                timezone: 'UTC',
                visualizationType: ChartDisplayType.ActionsStackedBar,
            })
            expect(config.yAxis?.scale).toBe('linear')
        })

        it('never emits trend lines (quill bar charts have no trend-line support)', () => {
            const ySeriesData = [ySeries('a', [1, 2], { display: { trendLine: true } })]
            const config = buildBarChartConfig({
                xData: dateXData,
                chartSettings: {},
                timezone: 'UTC',
                visualizationType: ChartDisplayType.ActionsBar,
                ySeriesData,
            })
            expect('trendLines' in config).toBe(false)
        })
    })

    describe('buildComboChartConfig', () => {
        const dateXData: AxisSeries<string> = {
            column: { name: 'day', type: { name: 'DATE', isNumerical: false }, label: 'day', dataIndex: 0 },
            data: ['2024-01-01', '2024-01-02'],
        }

        it.each([
            ['grouped bars for a bar graph', ChartDisplayType.ActionsBar, 'grouped'],
            ['stacked bars for a stacked bar graph', ChartDisplayType.ActionsStackedBar, 'stacked'],
            ['grouped bars for a line graph', ChartDisplayType.ActionsLineGraph, 'grouped'],
        ])('uses %s', (_name, visualizationType, expected) => {
            const config = buildComboChartConfig({
                xData: dateXData,
                chartSettings: {},
                timezone: 'UTC',
                visualizationType,
            })
            expect(config.barLayout).toBe(expected)
        })

        it('wires goal lines, legend, and a date x-axis formatter', () => {
            const config = buildComboChartConfig({
                xData: dateXData,
                chartSettings: { showLegend: true },
                timezone: 'UTC',
                visualizationType: ChartDisplayType.ActionsBar,
                goalLines: [{ label: 'Target', value: 100 }],
            })
            expect(config.xAxis?.tickFormatter).toBeInstanceOf(Function)
            expect(config.goalLines).toHaveLength(1)
            expect(config.legend).toEqual({ show: true, position: 'top', interactive: true })
            expect(config.tooltip).toMatchObject({ enabled: true, pinnable: true })
        })

        it('never emits trend lines (combo charts have no trend-line support)', () => {
            const config = buildComboChartConfig({
                xData: dateXData,
                chartSettings: {},
                timezone: 'UTC',
                visualizationType: ChartDisplayType.ActionsBar,
            })
            expect('trendLines' in config).toBe(false)
        })
    })
})
