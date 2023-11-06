import { useEffect, useRef } from 'react'
import {
    ActiveElement,
    Chart,
    ChartEvent,
    ChartItem,
    ChartType,
    TooltipModel,
    ChartOptions,
    ChartDataset,
    Plugin,
} from 'lib/Chart'
import 'chartjs-adapter-dayjs-3'
import { areObjectValuesEmpty } from '~/lib/utils'
import { GraphType } from '~/types'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import {
    ensureTooltipElement,
    filterNestedDataset,
    LineGraphProps,
    onChartClick,
    onChartHover,
} from 'scenes/insights/views/LineGraph/LineGraph'
import ReactDOM from 'react-dom'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { lineGraphLogic } from 'scenes/insights/views/LineGraph/lineGraphLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import ChartDataLabels, { Context } from 'chartjs-plugin-datalabels'

let timer: NodeJS.Timeout | null = null

function setTooltipPosition(chart: Chart, tooltipEl: HTMLElement): void {
    if (timer) {
        clearTimeout(timer)
    }
    timer = setTimeout(() => {
        const position = chart.canvas.getBoundingClientRect()

        tooltipEl.style.position = 'absolute'
        tooltipEl.style.left = position.left + window.pageXOffset + (chart.tooltip?.caretX || 0) + 8 + 'px'
        tooltipEl.style.top = position.top + window.pageYOffset + (chart.tooltip?.caretY || 0) + 8 + 'px'
    }, 25)
}

function getPercentageForDataPoint(context: Context): number {
    const total = context.dataset.data.reduce((a, b) => (a as number) + (b as number), 0) as number
    return ((context.dataset.data[context.dataIndex] as number) / total) * 100
}

export function PieChart({
    datasets: _datasets,
    hiddenLegendKeys,
    labels,
    type,
    onClick,
    ['data-attr']: dataAttr,
    trendsFilter,
    formula,
    showValueOnSeries,
    supportsPercentStackView,
    showPercentStackView,
    tooltip: tooltipConfig,
    showPersonsModal = true,
    labelGroupType,
}: LineGraphProps): JSX.Element {
    const isPie = type === GraphType.Pie
    const isPercentStackView = !!supportsPercentStackView && !!showPercentStackView

    if (!isPie) {
        throw new Error('PieChart must be a pie chart')
    }

    let datasets = _datasets

    const { createTooltipData } = useValues(lineGraphLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { highlightSeries } = useActions(insightLogic)
    const canvasRef = useRef<HTMLCanvasElement | null>(null)

    // Remove tooltip element on unmount
    useEffect(() => {
        return () => {
            const tooltipEl = document.getElementById('InsightTooltipWrapper')
            tooltipEl?.remove()
        }
    }, [])

    // Build chart
    useEffect(() => {
        // Hide intentionally hidden keys
        if (!areObjectValuesEmpty(hiddenLegendKeys)) {
            // If series are nested (for ActionsHorizontalBar and Pie), filter out the series by index
            datasets = filterNestedDataset(hiddenLegendKeys, datasets)
        }

        const processedDatasets = datasets.map((dataset) => dataset as ChartDataset<'pie'>)
        const onlyOneValue = processedDatasets?.[0]?.data?.length === 1
        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: 'pie',
            plugins: [ChartDataLabels as Plugin<'pie'>],
            data: {
                labels,
                datasets: processedDatasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                hover: {
                    mode: 'index',
                },
                layout: {
                    padding: {
                        top: 12, // 12 px so that the label isn't cropped
                        bottom: 20, // 12 px so that the label isn't cropped + 8 px of padding against the number below
                    },
                },
                borderWidth: 0,
                borderRadius: 0,
                hoverOffset: onlyOneValue ? 0 : 16, // don't offset hovered segment if it is 100%
                onHover(event: ChartEvent, _: ActiveElement[], chart: Chart) {
                    onChartHover(event, chart, onClick)
                },
                onClick: (event: ChartEvent, _: ActiveElement[], chart: Chart) => {
                    onChartClick(event, chart, datasets, onClick)
                },
                plugins: {
                    datalabels: {
                        color: 'white',
                        anchor: 'end',
                        backgroundColor: (context) => {
                            return context.dataset.backgroundColor?.[context.dataIndex] || 'black'
                        },
                        display: (context) => {
                            const percentage = getPercentageForDataPoint(context)
                            return showValueOnSeries !== false && // show if true or unset
                                context.dataset.data.length > 1 &&
                                percentage > 5
                                ? 'auto'
                                : false
                        },
                        padding: (context) => {
                            // in order to make numbers below 10 look circular we need a little padding
                            const value = context.dataset.data[context.dataIndex] as number
                            const paddingY = value < 10 ? 2 : 4
                            const paddingX = value < 10 ? 5 : 4
                            return { top: paddingY, bottom: paddingY, left: paddingX, right: paddingX }
                        },
                        formatter: (value: number, context) => {
                            if (isPercentStackView) {
                                const percentage = getPercentageForDataPoint(context)
                                return `${percentage.toFixed(1)}%`
                            }

                            return formatAggregationAxisValue(trendsFilter, value)
                        },
                        font: {
                            weight: 500,
                        },
                        borderRadius: 25,
                        borderWidth: 2,
                        borderColor: 'white',
                    },
                    legend: {
                        display: false,
                    },
                    crosshair: false,
                    tooltip: {
                        position: 'cursor',
                        enabled: false,
                        intersect: true,
                        external: function ({ chart, tooltip }: { chart: Chart; tooltip: TooltipModel<ChartType> }) {
                            if (!canvasRef.current) {
                                return
                            }

                            const tooltipEl = ensureTooltipElement()
                            if (tooltip.opacity === 0) {
                                // remove highlight from the legend
                                if (trendsFilter?.show_legend) {
                                    highlightSeries(null)
                                }
                                tooltipEl.style.opacity = '0'
                                return
                            }

                            // Set caret position
                            // Reference: https://www.chartjs.org/docs/master/configuration/tooltip.html
                            tooltipEl.classList.remove('above', 'below', 'no-transform')
                            tooltipEl.classList.add(tooltip.yAlign || 'no-transform')
                            tooltipEl.style.opacity = '1'
                            tooltipEl.style.display = 'initial'

                            if (tooltip.body) {
                                const referenceDataPoint = tooltip.dataPoints[0] // Use this point as reference to get the date
                                const dataset = datasets[referenceDataPoint.datasetIndex]
                                const seriesData = createTooltipData(
                                    tooltip.dataPoints,
                                    (dp) => dp.datasetIndex >= 0 && dp.datasetIndex < _datasets.length
                                )

                                highlightSeries(seriesData[0].dataIndex)

                                ReactDOM.render(
                                    <InsightTooltip
                                        seriesData={seriesData}
                                        hideColorCol={!!tooltipConfig?.hideColorCol}
                                        showHeader={false}
                                        renderSeries={(value: React.ReactNode, datum: SeriesDatum) => {
                                            const hasBreakdown =
                                                datum.breakdown_value !== undefined && !!datum.breakdown_value
                                            return (
                                                <div className="datum-label-column">
                                                    {!formula && (
                                                        <SeriesLetter
                                                            className="mr-2"
                                                            hasBreakdown={hasBreakdown}
                                                            seriesIndex={datum?.action?.order ?? datum.id}
                                                        />
                                                    )}
                                                    <div className="flex flex-col">
                                                        {hasBreakdown && !formula && datum.breakdown_value}
                                                        {value}
                                                    </div>
                                                </div>
                                            )
                                        }}
                                        renderCount={
                                            tooltipConfig?.renderCount ||
                                            ((value: number): string => {
                                                const total = dataset.data.reduce((a: number, b: number) => a + b, 0)
                                                const percentageLabel: number = parseFloat(
                                                    ((value / total) * 100).toFixed(1)
                                                )
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
                                    />,
                                    tooltipEl
                                )
                            }

                            setTooltipPosition(chart, tooltipEl)
                        },
                    },
                },
            } as ChartOptions<'pie'>,
        })
        return () => newChart.destroy()
    }, [datasets, hiddenLegendKeys])

    return (
        <div className="absolute w-full h-full" data-attr={dataAttr}>
            <canvas ref={canvasRef} />
        </div>
    )
}
