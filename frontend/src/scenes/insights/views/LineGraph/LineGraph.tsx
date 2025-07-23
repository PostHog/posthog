import 'chartjs-adapter-dayjs-3'

import { DeepPartial } from 'chart.js/dist/types/utils'
import annotationPlugin from 'chartjs-plugin-annotation'
import ChartDataLabels from 'chartjs-plugin-datalabels'
import ChartjsPluginStacked100, { ExtendedChartData } from 'chartjs-plugin-stacked100'
import clsx from 'clsx'
import { useValues } from 'kea'
import { LegendOptions, ScaleOptions } from 'lib/Chart'
import {
    ActiveElement,
    Chart,
    ChartDataset,
    ChartEvent,
    ChartItem,
    ChartOptions,
    ChartType,
    Color,
    GridLineOptions,
    InteractionItem,
    ScriptableLineSegmentContext,
    TickOptions,
    TooltipModel,
    TooltipOptions,
} from 'lib/Chart'
import { getBarColorFromStatus, getGraphColors } from 'lib/colors'
import { AnnotationsOverlay } from 'lib/components/AnnotationsOverlay'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'
import { createRoot, Root } from 'react-dom/client'
import { formatAggregationAxisValue, formatPercentStackAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { TooltipConfig } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { PieChart } from 'scenes/insights/views/LineGraph/PieChart'
import { createTooltipData } from 'scenes/insights/views/LineGraph/tooltip-data'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { hexToRGBA, lightenDarkenColor } from '~/lib/utils'
import { groupsModel } from '~/models/groupsModel'
import { GoalLine, TrendsFilter } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { GraphDataset, GraphPoint, GraphPointPayload, GraphType } from '~/types'

let tooltipRoot: Root

export function ensureTooltip(): [Root, HTMLElement] {
    let tooltipEl = document.getElementById('InsightTooltipWrapper')

    if (!tooltipEl || !tooltipRoot) {
        if (!tooltipEl) {
            tooltipEl = document.createElement('div')
            tooltipEl.id = 'InsightTooltipWrapper'
            tooltipEl.classList.add('InsightTooltipWrapper')
            document.body.appendChild(tooltipEl)
        }

        tooltipRoot = createRoot(tooltipEl)
    }
    return [tooltipRoot, tooltipEl]
}

export function hideTooltip(): void {
    const tooltipEl = document.getElementById('InsightTooltipWrapper')
    if (tooltipEl) {
        tooltipEl.style.opacity = '0'
    }
}

function truncateString(str: string, num: number): string {
    if (str.length > num) {
        return str.slice(0, num) + ' ...'
    }
    return str
}

const RESOLVED_COLOR_MAP = new Map<string, string>()
function resolveVariableColor(color: string | undefined): string | undefined {
    if (!color) {
        return color
    }

    if (RESOLVED_COLOR_MAP.has(color)) {
        return RESOLVED_COLOR_MAP.get(color)
    }

    // Cache complex variables to avoid the `getComputedStyle` call on every call
    if (color.startsWith('var(--')) {
        const replaced = color.replace('var(', '').replace(')', '')
        const computedColor = getComputedStyle(document.documentElement).getPropertyValue(replaced)
        RESOLVED_COLOR_MAP.set(color, computedColor)
        return computedColor
    }

    // Optimize to avoid the `startsWith` check on every call
    RESOLVED_COLOR_MAP.set(color, color)

    return color
}

export function onChartClick(
    event: ChartEvent,
    chart: Chart,
    datasets: GraphDataset[],
    onClick?: { (payload: GraphPointPayload): void | undefined }
): void {
    const nativeEvent = event.native
    if (!nativeEvent) {
        return
    }
    // Get all points along line
    const sortDirection = 'y'
    const sortPoints = (a: InteractionItem, b: InteractionItem): number =>
        Math.abs(a.element[sortDirection] - (event[sortDirection] ?? 0)) -
        Math.abs(b.element[sortDirection] - (event[sortDirection] ?? 0))
    const pointsIntersectingLine = chart
        .getElementsAtEventForMode(
            nativeEvent,
            'index',
            {
                intersect: false,
            },
            true
        )
        .sort(sortPoints)
    // Get all points intersecting clicked point
    const pointsIntersectingClick = chart
        .getElementsAtEventForMode(
            nativeEvent,
            'point',
            {
                intersect: true,
            },
            true
        )
        .sort(sortPoints)

    if (!pointsIntersectingClick.length && !pointsIntersectingLine.length) {
        return
    }

    const clickedPointNotLine = pointsIntersectingClick.length !== 0

    // Take first point when clicking a specific point.
    const referencePoint: GraphPoint = clickedPointNotLine
        ? { ...pointsIntersectingClick[0], dataset: datasets[pointsIntersectingClick[0].datasetIndex] }
        : { ...pointsIntersectingLine[0], dataset: datasets[pointsIntersectingLine[0].datasetIndex] }

    const crossDataset = datasets
        .filter((_dt) => !_dt.dotted)
        .map((_dt) => ({
            ..._dt,
            personUrl: _dt.persons_urls?.[referencePoint.index].url,
            pointValue: _dt.data[referencePoint.index],
        }))

    onClick?.({
        points: {
            pointsIntersectingLine: pointsIntersectingLine.map((p) => ({
                ...p,
                dataset: datasets[p.datasetIndex],
            })),
            pointsIntersectingClick: pointsIntersectingClick.map((p) => ({
                ...p,
                dataset: datasets[p.datasetIndex],
            })),
            clickedPointNotLine,
            referencePoint,
        },
        index: referencePoint.index,
        crossDataset,
        seriesId: datasets[referencePoint.datasetIndex].id,
    })
}

export function onChartHover(
    event: ChartEvent,
    chart: Chart,
    onClick?: ((payload: GraphPointPayload) => void) | undefined
): void {
    const nativeEvent = event.native
    if (!nativeEvent) {
        return
    }

    const target = nativeEvent?.target as HTMLDivElement
    const point = chart.getElementsAtEventForMode(nativeEvent, 'index', {}, true)

    // Give the chart `cursor: pointer` only when hovering over a clickable area
    target.style.cursor = onClick && point.length ? 'pointer' : 'default'
}

export const filterNestedDataset = (
    hiddenLegendIndexes: number[] | undefined,
    datasets: GraphDataset[]
): GraphDataset[] => {
    if (!hiddenLegendIndexes) {
        return datasets
    }
    // If series are nested (for ActionsHorizontalBar and Pie), filter out the series by index
    const filterFn = (_: any, i: number): boolean => !hiddenLegendIndexes?.includes(i)
    return datasets.map((_data) => {
        // Performs a filter transformation on properties that contain arrayed data
        return Object.fromEntries(
            Object.entries(_data).map(([key, val]) =>
                Array.isArray(val) && val.length === datasets?.[0]?.actions?.length
                    ? [key, val?.filter(filterFn)]
                    : [key, val]
            )
        ) as GraphDataset
    })
}

function createPinstripePattern(color: string, isDarkMode: boolean): CanvasPattern {
    const stripeWidth = 8 // 0.5rem
    const stripeAngle = -22.5

    // create the canvas and context
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = stripeWidth * 2

    const ctx = canvas.getContext('2d')!

    // fill the canvas with given color
    ctx.fillStyle = color
    ctx.fillRect(0, 0, canvas.width, canvas.height)

    // overlay half-transparent black / white stripes
    ctx.fillStyle = isDarkMode ? 'rgba(35, 36, 41, 0.5)' : 'rgba(255, 255, 255, 0.5)'
    ctx.fillRect(0, stripeWidth, 1, 2 * stripeWidth)

    // create a canvas pattern and rotate it

    const pattern = ctx.createPattern(canvas, 'repeat')!
    const xAx = Math.cos(stripeAngle)
    const xAy = Math.sin(stripeAngle)
    pattern.setTransform(new DOMMatrix([xAx, xAy, -xAy, xAx, 0, 0]))

    return pattern
}

export interface LineGraphProps {
    datasets: GraphDataset[]
    hiddenLegendIndexes?: number[] | undefined
    labels: string[]
    type: GraphType
    isInProgress?: boolean
    onClick?: (payload: GraphPointPayload) => void
    ['data-attr']: string
    inSharedMode?: boolean
    showPersonsModal?: boolean
    tooltip?: TooltipConfig
    inSurveyView?: boolean
    isArea?: boolean
    incompletenessOffsetFromEnd?: number // Number of data points at end of dataset to replace with a dotted line. Only used in line graphs.
    labelGroupType: number | 'people' | 'none'
    trendsFilter?: TrendsFilter | null
    formula?: string | null
    showValuesOnSeries?: boolean | null
    showPercentStackView?: boolean | null
    supportsPercentStackView?: boolean
    showPercentView?: boolean | null
    hideAnnotations?: boolean
    hideXAxis?: boolean
    hideYAxis?: boolean
    legend?: DeepPartial<LegendOptions<ChartType>>
    yAxisScaleType?: string | null
    showMultipleYAxes?: boolean | null
    goalLines?: GoalLine[]
    isStacked?: boolean
}

export const LineGraph = (props: LineGraphProps): JSX.Element => {
    return (
        <ErrorBoundary exceptionProps={{ feature: 'LineGraph' }}>
            {props.type === GraphType.Pie ? <PieChart {...props} /> : <LineGraph_ {...props} />}
        </ErrorBoundary>
    )
}

/**
 * Chart.js in log scale refuses to render points that are 0 - as log(0) is undefined - hence a special value for that case.
 */
const LOG_ZERO = 1e-10

export function LineGraph_({
    datasets: _datasets,
    hiddenLegendIndexes,
    labels,
    type,
    isInProgress = false,
    onClick,
    ['data-attr']: dataAttr,
    showPersonsModal = true,
    inSurveyView,
    isArea = false,
    incompletenessOffsetFromEnd = -1,
    tooltip: tooltipConfig,
    labelGroupType,
    trendsFilter,
    formula,
    showValuesOnSeries,
    showPercentStackView,
    supportsPercentStackView,
    showPercentView,
    hideAnnotations,
    hideXAxis,
    hideYAxis,
    yAxisScaleType,
    showMultipleYAxes = false,
    legend = { display: false },
    goalLines: _goalLines,
    isStacked = true,
}: LineGraphProps): JSX.Element {
    const originalDatasets = _datasets
    let datasets = _datasets

    const { aggregationLabel } = useValues(groupsModel)
    const { isDarkModeOn } = useValues(themeLogic)

    const { insightProps, insight } = useValues(insightLogic)
    const { timezone, isTrends, breakdownFilter, query, interval, insightData } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { theme, getTrendsColor } = useValues(trendsDataLogic(insightProps))

    const hideTooltipOnScroll = isInsightVizNode(query) ? query.hideTooltipOnScroll : undefined

    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [lineChart, setLineChart] = useState<Chart<ChartType, any, string>>()

    // Relying on useResizeObserver instead of Chart's onResize because the latter was not reliable
    const { width: chartWidth, height: chartHeight } = useResizeObserver({ ref: canvasRef })

    const colors = getGraphColors()
    const isHorizontal = type === GraphType.HorizontalBar
    const isPie = type === GraphType.Pie
    if (isPie) {
        throw new Error('Use PieChart not LineGraph for this `GraphType`')
    }

    const isBar = [GraphType.Bar, GraphType.HorizontalBar, GraphType.Histogram].includes(type)
    const isBackgroundBasedGraphType = [GraphType.Bar].includes(type)
    const isPercentStackView = !!supportsPercentStackView && !!showPercentStackView
    const showAnnotations = isTrends && !isHorizontal && !hideAnnotations
    const isLog10 = yAxisScaleType === 'log10' // Currently log10 is the only logarithmic scale supported

    // Add scrollend event on main element to hide tooltips when scrolling
    useEffect(() => {
        if (!hideTooltipOnScroll) {
            return
        }

        // Scroll events happen on the main element due to overflow-y: scroll
        // but we need to make sure it exists before adding the event listener,
        // e.g: it does not exist in the shared pages
        const main = document.getElementsByTagName('main')[0]
        if (main) {
            main.addEventListener('scrollend', hideTooltip)
        }

        return () => {
            if (main) {
                main.removeEventListener('scrollend', hideTooltip)
            }
        }
    }, [hideTooltipOnScroll])

    // Remove tooltip element on unmount
    useEffect(() => {
        return () => {
            const tooltipEl = document.getElementById('InsightTooltipWrapper')
            tooltipEl?.remove()
        }
    }, [])

    // Add event listeners to canvas
    useEffect(() => {
        const canvas = canvasRef.current

        if (canvas) {
            const handleEvent = (event: Event): void => {
                if ((window.performance as any)?.memory) {
                    console.error(event, {
                        usedJSHeapSize:
                            ((window.performance as any)?.memory.usedJSHeapSize / 1024 / 1024).toFixed(2) + ' MB',
                        totalJSHeapSize:
                            ((window.performance as any)?.memory.totalJSHeapSize / 1024 / 1024).toFixed(2) + ' MB',
                        jsHeapSizeLimit:
                            ((window.performance as any)?.memory.jsHeapSizeLimit / 1024 / 1024).toFixed(2) + ' MB',
                    })
                } else {
                    console.error(event)
                }

                posthog.captureException(event)
            }

            canvas.addEventListener('contextlost', handleEvent)
            canvas.addEventListener('webglcontextcreationerror', handleEvent)
            canvas.addEventListener('webglcontextlost', handleEvent)

            return () => {
                canvas.removeEventListener('contextlost', handleEvent)
                canvas.removeEventListener('webglcontextcreationerror', handleEvent)
                canvas.removeEventListener('webglcontextlost', handleEvent)
            }
        }
    }, [])

    function processDataset(dataset: ChartDataset<any>, index: number): ChartDataset<any> {
        const isPrevious = !!dataset.compare && dataset.compare_label === 'previous'

        const themeColor = dataset?.status
            ? getBarColorFromStatus(dataset.status)
            : isHorizontal
            ? dataset.backgroundColor
            : getTrendsColor(dataset) || '#000000' // Default to black if no color found
        const mainColor = isPrevious ? `${themeColor}80` : themeColor

        const hoverColor = dataset?.status ? getBarColorFromStatus(dataset.status, true) : mainColor

        let backgroundColor: string | undefined = undefined
        if (isBackgroundBasedGraphType) {
            backgroundColor = mainColor
        } else if (isArea) {
            backgroundColor = hexToRGBA(mainColor, 0.5)
        }

        let adjustedData = dataset.data
        if (isLog10 && Array.isArray(adjustedData)) {
            // In log scale, transform zeros to our special value
            adjustedData = adjustedData.map((value) => (value === 0 ? LOG_ZERO : value))
        }

        // Transform data to percentages if showPercentView is enabled
        if (showPercentView && Array.isArray(adjustedData)) {
            const count = dataset.count
            adjustedData = adjustedData.map((value) => (typeof value === 'number' ? (value / count) * 100 : value))
        }

        // `horizontalBar` colors are set in `ActionsHorizontalBar.tsx` and overridden in spread of `dataset` below
        return {
            borderColor: mainColor,
            hoverBorderColor: isBackgroundBasedGraphType ? lightenDarkenColor(mainColor, -20) : hoverColor,
            hoverBackgroundColor: isBackgroundBasedGraphType ? lightenDarkenColor(mainColor, -20) : undefined,
            fill: isArea ? 'origin' : false,
            backgroundColor,
            segment: {
                borderDash: (ctx: ScriptableLineSegmentContext) => {
                    // If chart is line graph, show dotted lines for incomplete data
                    if (!(type === GraphType.Line && isInProgress)) {
                        return undefined
                    }

                    const isIncomplete = ctx.p1DataIndex >= dataset.data.length + incompletenessOffsetFromEnd
                    const isActive = !dataset.compare || dataset.compare_label != 'previous'
                    // if last date is still active show dotted line
                    return isIncomplete && isActive ? [10, 10] : undefined
                },
                backgroundColor: (ctx: ScriptableLineSegmentContext) => {
                    // If chart is area graph, show pinstripe pattern for incomplete data
                    if (!(type === GraphType.Line && isInProgress && isArea)) {
                        return undefined
                    }

                    const isIncomplete = ctx.p1DataIndex >= dataset.data.length + incompletenessOffsetFromEnd
                    const isActive = !dataset.compare || dataset.compare_label != 'previous'
                    // if last date is still active show dotted line
                    const areaBackgroundColor = hexToRGBA(mainColor, 0.5)
                    const areaIncompletePattern = createPinstripePattern(areaBackgroundColor, isDarkModeOn)
                    return isIncomplete && isActive ? areaIncompletePattern : undefined
                },
            },
            borderWidth: isBar ? 0 : 2,
            pointRadius: 0,
            hitRadius: 0,
            order: 1,
            ...(type === GraphType.Histogram ? { barPercentage: 1 } : {}),
            ...dataset,
            data: adjustedData,
            hoverBorderWidth: isBar ? 0 : 2,
            hoverBorderRadius: isBar ? 0 : 2,
            type: (isHorizontal ? GraphType.Bar : type) as ChartType,
            yAxisID: type === GraphType.Line && showMultipleYAxes && index > 0 ? `y${index}` : 'y',
        }
    }

    function formatYAxisTick(value: number | string): string {
        if (showPercentView) {
            return `${Number(value).toFixed(1)}%`
        }
        return formatPercentStackAxisValue(trendsFilter, value, isPercentStackView)
    }

    function generateYaxesForLineGraph(
        dataSetCount: number,
        seriesNonZeroMin: number,
        goalLines: GoalLine[],
        goalLinesY: number[],
        goalLinesWithColor: GoalLine[],
        tickOptions: Partial<TickOptions>,
        precision: number,
        gridOptions: Partial<GridLineOptions>
    ): Record<string, ScaleOptions<'linear' | 'logarithmic'>> {
        const defaultYAxisConfig = {
            display: !hideYAxis,
            ...(isLog10
                ? { type: 'logarithmic' as const, min: Math.pow(10, Math.ceil(Math.log10(seriesNonZeroMin)) - 1) }
                : { type: 'linear' as const }),
            beginAtZero: true,
            stacked: showPercentStackView || isArea,
            ticks: {
                ...tickOptions,
                display: !hideYAxis,
                ...(yAxisScaleType !== 'log10' && { precision }), // Precision is not supported for the log scale
                callback: formatYAxisTick,
                color: (context: any) => {
                    if (context.tick) {
                        for (const annotation of goalLinesWithColor) {
                            if (context.tick.value === annotation.value) {
                                return resolveVariableColor(annotation.borderColor)
                            }
                        }
                    }

                    return colors.axisLabel as Color
                },
            },
            afterTickToLabelConversion: (axis: { id: string; ticks: { value: number }[] }) => {
                if (!axis.id.startsWith('y')) {
                    return
                }

                const nonAnnotationTicks = axis.ticks.filter(
                    ({ value }: { value: number }) => !goalLinesY.includes(value)
                )
                const annotationTicks = goalLines.map((value) => ({
                    value: value.value,
                    label: `⬤ ${formatYAxisTick(value.value)}`,
                }))

                // Guarantee that all annotations exist as ticks
                axis.ticks = [...nonAnnotationTicks, ...annotationTicks]
            },
            grid: gridOptions,
        }

        type YAxisConfig = typeof defaultYAxisConfig & {
            position: 'left' | 'right'
        }

        const axes: Record<string, YAxisConfig> = {
            y: {
                ...defaultYAxisConfig,
                position: 'left',
            },
        }

        if (showMultipleYAxes) {
            for (let i = 1; i < dataSetCount; i++) {
                axes[`y${i}`] = {
                    ...defaultYAxisConfig,
                    position: i % 2 === 0 ? 'left' : 'right',
                }
            }
        }

        return axes
    }

    // Build chart
    useEffect(() => {
        // Hide intentionally hidden keys
        if (hiddenLegendIndexes && hiddenLegendIndexes.length > 0) {
            if (isHorizontal) {
                datasets = filterNestedDataset(hiddenLegendIndexes, datasets)
            } else {
                datasets = datasets.filter((data) => !hiddenLegendIndexes?.includes(data.id))
            }
        }

        datasets = datasets.map(processDataset)

        const seriesNonZeroMax = Math.max(...datasets.flatMap((d) => d.data).filter((n) => !!n && n !== LOG_ZERO))
        const seriesNonZeroMin = Math.min(...datasets.flatMap((d) => d.data).filter((n) => !!n && n !== LOG_ZERO))
        const precision = seriesNonZeroMax < 2 ? 2 : seriesNonZeroMax < 5 ? 1 : 0
        const goalLines = (_goalLines || []).filter(
            (goalLine) => goalLine.displayIfCrossed !== false || goalLine.value >= seriesNonZeroMax
        )
        const goalLinesY = goalLines.map((a) => a.value)
        const goalLinesWithColor = goalLines.filter((goalLine) => Boolean(goalLine.borderColor))

        const tickOptions: Partial<TickOptions> = {
            color: colors.axisLabel as Color,
            font: {
                family: '"Emoji Flags Polyfill", -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
                size: 12,
                weight: 'normal',
            },
        }
        const gridOptions: Partial<GridLineOptions> = {
            color: (context) => {
                if (goalLinesY.includes(context.tick?.value) || showMultipleYAxes) {
                    return 'transparent'
                }

                return colors.axisLine as Color
            },
            tickColor: (context) => {
                if (goalLinesY.includes(context.tick?.value)) {
                    return 'transparent'
                }

                return colors.axisLine as Color
            },
            tickBorderDash: [4, 2],
        }

        const tooltipOptions: Partial<TooltipOptions> = {
            enabled: false, // disable builtin tooltip (use custom markup)
            mode: 'nearest',
            // If bar, we want to only show the tooltip for what we're hovering over
            // to avoid confusion
            axis: isHorizontal ? 'y' : 'x',
            intersect: false,
            itemSort: (a, b) => a.label.localeCompare(b.label),
        }

        const options: ChartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            elements: {
                line: {
                    tension: 0,
                },
            },
            interaction: {
                includeInvisible: true, // Only important for log scale, where 0 values are always below the minimum
            },
            plugins: {
                stacked100: { enable: isPercentStackView, precision: 1 },
                datalabels: {
                    color: 'white',
                    anchor: (context) => {
                        // the type here doesn't allow for undefined, but we see errors where things are undefined
                        const datum = context.dataset?.data[context.dataIndex]
                        return typeof datum !== 'number' ? 'end' : datum > 0 ? 'end' : 'start'
                    },
                    backgroundColor: (context) => {
                        // the type here doesn't allow for undefined, but we see errors where things are undefined
                        return (context.dataset?.borderColor as string) || 'black'
                    },
                    display: (context) => {
                        // the type here doesn't allow for undefined, but we see errors where things are undefined
                        const datum = context.dataset?.data[context.dataIndex]
                        if (showValuesOnSeries && inSurveyView) {
                            return true
                        }
                        return showValuesOnSeries === true && typeof datum === 'number' && datum !== 0 ? 'auto' : false
                    },
                    formatter: (value: number, context) => {
                        // the type here doesn't allow for undefined, but we see errors where things are undefined
                        const data = context.chart?.data as ExtendedChartData
                        if (!data) {
                            return ''
                        }
                        const { datasetIndex, dataIndex } = context
                        const percentageValue = data.calculatedData?.[datasetIndex][dataIndex]
                        return formatPercentStackAxisValue(trendsFilter, percentageValue || value, isPercentStackView)
                    },
                    borderWidth: 2,
                    borderRadius: 4,
                    borderColor: 'white',
                },
                legend: legend,
                annotation: {
                    annotations: goalLines.reduce((acc: Record<string, any>, annotation, idx) => {
                        acc[`line-${idx}`] = {
                            type: 'line',
                            yMin: annotation.value,
                            yMax: annotation.value,
                            borderColor: resolveVariableColor(annotation.borderColor) || 'rgb(255, 99, 132)',
                            label: {
                                content: annotation.label,
                                display: annotation.displayLabel ?? true,
                                position: 'end',
                            },
                            borderWidth: 1,
                            borderDash: [5, 8],
                        }

                        return acc
                    }, {}),
                },
                tooltip: {
                    ...tooltipOptions,
                    external({ tooltip }: { chart: Chart; tooltip: TooltipModel<ChartType> }) {
                        if (!canvasRef.current) {
                            return
                        }

                        const [tooltipRoot, tooltipEl] = ensureTooltip()
                        if (tooltip.opacity === 0) {
                            tooltipEl.style.opacity = '0'
                            return
                        }

                        // Set caret position
                        // Reference: https://www.chartjs.org/docs/master/configuration/tooltip.html
                        tooltipEl.classList.remove('above', 'below', 'no-transform')
                        tooltipEl.classList.add(tooltip.yAlign || 'no-transform')
                        tooltipEl.style.opacity = '1'

                        if (tooltip.body) {
                            const referenceDataPoint = tooltip.dataPoints[0] // Use this point as reference to get the date
                            const dataset = datasets[referenceDataPoint.datasetIndex]
                            const date = dataset?.days?.[referenceDataPoint.dataIndex]
                            const seriesData = createTooltipData(tooltip.dataPoints, (dp) => {
                                const hasDotted =
                                    datasets.some((d) => d.dotted) &&
                                    dp.dataIndex - datasets?.[dp.datasetIndex]?.data?.length >=
                                        incompletenessOffsetFromEnd
                                return (
                                    dp.datasetIndex >= (hasDotted ? _datasets.length : 0) &&
                                    dp.datasetIndex < (hasDotted ? _datasets.length * 2 : _datasets.length)
                                )
                            })

                            tooltipRoot.render(
                                <InsightTooltip
                                    date={date}
                                    altTitle={() =>
                                        typeof date === 'number'
                                            ? dataset?.labels?.[referenceDataPoint.dataIndex]
                                            : null
                                    }
                                    timezone={timezone}
                                    seriesData={seriesData}
                                    breakdownFilter={breakdownFilter}
                                    interval={interval}
                                    dateRange={insightData?.resolved_date_range}
                                    renderSeries={(value, datum) => {
                                        const hasBreakdown =
                                            datum.breakdown_value !== undefined && !!datum.breakdown_value

                                        return (
                                            <div className="datum-label-column">
                                                {!formula && (
                                                    <SeriesLetter
                                                        className="mr-2"
                                                        hasBreakdown={hasBreakdown}
                                                        seriesIndex={datum.action?.order ?? datum.id}
                                                        seriesColor={datum.color}
                                                    />
                                                )}
                                                {value}
                                            </div>
                                        )
                                    }}
                                    renderCount={
                                        tooltipConfig?.renderCount ||
                                        ((value: number): string => {
                                            if (showPercentView) {
                                                const series = seriesData.find((s) => s.count === value)
                                                const datasetIndex = series?.datasetIndex
                                                const dataIndex = series?.dataIndex
                                                if (datasetIndex !== undefined && dataIndex !== undefined) {
                                                    const originalDataset = originalDatasets[datasetIndex]
                                                    const originalValue = originalDataset.data?.[dataIndex]

                                                    if (originalValue !== undefined && originalValue !== null) {
                                                        return `${value.toFixed(1)}% (${formatAggregationAxisValue(
                                                            trendsFilter,
                                                            originalValue
                                                        )})`
                                                    }
                                                }
                                            }

                                            if (!isPercentStackView) {
                                                return formatAggregationAxisValue(trendsFilter, value)
                                            }

                                            const total = seriesData.reduce((a, b) => a + b.count, 0)
                                            const percentageLabel: number = parseFloat(
                                                ((value / total) * 100).toFixed(1)
                                            )

                                            const isNaN = Number.isNaN(percentageLabel)

                                            if (isNaN) {
                                                return formatAggregationAxisValue(trendsFilter, value)
                                            }

                                            return `${formatAggregationAxisValue(
                                                trendsFilter,
                                                value
                                            )} (${percentageLabel}%)`
                                        })
                                    }
                                    hideInspectActorsSection={!onClick || !showPersonsModal}
                                    groupTypeLabel={
                                        labelGroupType === 'people'
                                            ? 'people'
                                            : labelGroupType === 'none'
                                            ? ''
                                            : aggregationLabel(labelGroupType).plural
                                    }
                                    {...tooltipConfig}
                                />
                            )
                        }

                        const bounds = canvasRef.current.getBoundingClientRect()
                        const horizontalBarTopOffset = isHorizontal ? tooltip.caretY - tooltipEl.clientHeight / 2 : 0
                        const tooltipClientTop = bounds.top + window.pageYOffset + horizontalBarTopOffset

                        const chartClientLeft = bounds.left + window.pageXOffset
                        const defaultOffsetLeft = Math.max(chartClientLeft, chartClientLeft + tooltip.caretX + 8)
                        const maxXPosition = bounds.right - tooltipEl.clientWidth
                        const tooltipClientLeft =
                            defaultOffsetLeft > maxXPosition
                                ? chartClientLeft + tooltip.caretX - tooltipEl.clientWidth - 8 // If tooltip is too large (or close to the edge), show it to the left of the data point instead
                                : defaultOffsetLeft

                        tooltipEl.style.top = tooltipClientTop + 'px'
                        tooltipEl.style.left = tooltipClientLeft + 'px'
                    },
                },
                ...(!isBar
                    ? {
                          crosshair: {
                              snap: {
                                  enabled: true, // Snap crosshair to data points
                              },
                              sync: {
                                  enabled: false, // Sync crosshairs across multiple Chartjs instances
                              },
                              zoom: {
                                  enabled: false, // Allow drag to zoom
                              },
                              line: {
                                  color: colors.crosshair ?? undefined,
                                  width: 1,
                              },
                          },
                      }
                    : {
                          crosshair: false,
                      }),
            },
            hover: {
                mode: isBar ? 'point' : 'nearest',
                axis: isHorizontal ? 'y' : 'x',
                intersect: false,
            },
            onHover(event: ChartEvent, _: ActiveElement[], chart: Chart) {
                onChartHover(event, chart, onClick)
            },
            onClick: (event: ChartEvent, _: ActiveElement[], chart: Chart) => {
                onChartClick(event, chart, datasets, onClick)
            },
        }

        const truncateRows = !inSurveyView && !!insightProps.dashboardId

        if (type === GraphType.Bar) {
            if (hideXAxis || hideYAxis) {
                options.layout = { padding: 20 }
            }
            options.scales = {
                x: {
                    display: !hideXAxis,
                    beginAtZero: true,
                    stacked: isStacked,
                    ticks: {
                        ...tickOptions,
                        precision,
                        ...(inSurveyView
                            ? {
                                  padding: 10,
                                  font: {
                                      size: 14,
                                      weight: 'bold',
                                  },
                              }
                            : {}),
                    },
                    grid: inSurveyView ? { display: false } : gridOptions,
                },
                y: {
                    display: !hideYAxis,
                    beginAtZero: true,
                    stacked: isStacked,
                    ticks: {
                        ...tickOptions,
                        display: !hideYAxis,
                        precision,
                        callback: (value) => {
                            return formatPercentStackAxisValue(trendsFilter, value, isPercentStackView)
                        },
                    },
                    grid: gridOptions,
                },
            }
        } else if (type === GraphType.Line) {
            if (hideXAxis || hideYAxis) {
                options.layout = { padding: 20 }
            }
            options.scales = {
                x: {
                    display: !hideXAxis,
                    beginAtZero: true,
                    ticks: tickOptions,
                    grid: {
                        ...gridOptions,
                        drawOnChartArea: false,
                        tickLength: 12,
                    },
                },
                ...generateYaxesForLineGraph(
                    datasets.length,
                    seriesNonZeroMin,
                    goalLines,
                    goalLinesY,
                    goalLinesWithColor,
                    tickOptions,
                    precision,
                    gridOptions
                ),
            }
        } else if (isHorizontal) {
            if (hideXAxis || hideYAxis) {
                options.layout = { padding: 20 }
            }
            options.scales = {
                x: {
                    display: !hideXAxis,
                    beginAtZero: true,
                    ticks: {
                        display: !hideXAxis,
                        ...tickOptions,
                        precision,
                        callback: (value) => {
                            return formatPercentStackAxisValue(trendsFilter, value, isPercentStackView)
                        },
                    },
                    grid: gridOptions,
                },
                y: {
                    display: true,
                    beforeFit: (scale) => {
                        scale.ticks = scale.ticks.map((tick) => {
                            if (typeof tick.label === 'string') {
                                return { ...tick, label: truncateString(tick.label, 50) }
                            }
                            return tick
                        })

                        const ROW_HEIGHT = inSurveyView ? 30 : 20
                        const height = scale.ticks.length * ROW_HEIGHT
                        const parentNode: any = scale.chart?.canvas?.parentNode
                        parentNode.style.height = `${height}px`

                        if (truncateRows) {
                            // Display only as many bars, as we can fit labels
                            // Important: Make sure the query result does not deliver more data than we can display
                            // See apply_dashboard_filters function in query runners
                            scale.max = scale.ticks.length
                        }
                    },
                    beginAtZero: true,
                    ticks: {
                        ...tickOptions,
                        precision,
                        stepSize: !truncateRows ? 1 : undefined,
                        autoSkip: !truncateRows ? false : undefined,
                        callback: function _renderYLabel(_, i) {
                            const d = datasets?.[0]
                            if (!d) {
                                return ''
                            }
                            // prefer custom name, then label, then action name
                            let labelDescriptors: (string | number | undefined | null)[]
                            if (d.actions?.[i]?.custom_name) {
                                labelDescriptors = [
                                    d.actions?.[i]?.custom_name,
                                    d.breakdownLabels?.[i],
                                    d.compareLabels?.[i],
                                ]
                            } else if (d.breakdownLabels?.[i]) {
                                labelDescriptors = [d.actions?.[i]?.name, d.breakdownLabels[i], d.compareLabels?.[i]]
                            } else if (d.labels?.[i]) {
                                labelDescriptors = [d.labels[i], d.compareLabels?.[i]]
                            } else {
                                labelDescriptors = [d.actions?.[i]?.name, d.breakdownLabels?.[i], d.compareLabels?.[i]]
                            }
                            return labelDescriptors.filter((l) => !!l).join(' - ')
                        },
                    },
                    grid: {
                        ...gridOptions,
                        display: !inSurveyView,
                    },
                },
            }
            options.indexAxis = 'y'
        }
        Chart.register(ChartjsPluginStacked100)
        Chart.register(annotationPlugin)

        const chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: (isBar ? GraphType.Bar : type) as ChartType,
            data: { labels, datasets },
            options,
            plugins: [ChartDataLabels],
        })

        setLineChart(chart)

        return () => chart.destroy()
    }, [
        datasets,
        hiddenLegendIndexes,
        isDarkModeOn,
        trendsFilter,
        formula,
        showValuesOnSeries,
        showPercentStackView,
        showMultipleYAxes,
        _goalLines,
        theme,
    ])

    return (
        <div className={clsx('LineGraph w-full grow relative overflow-hidden')} data-attr={dataAttr}>
            <canvas ref={canvasRef} />
            {showAnnotations && lineChart && chartWidth && chartHeight ? (
                <AnnotationsOverlay
                    chart={lineChart}
                    dates={datasets[0]?.days || []}
                    chartWidth={chartWidth}
                    chartHeight={chartHeight}
                    insightNumericId={insight.id || 'new'}
                />
            ) : null}
        </div>
    )
}
