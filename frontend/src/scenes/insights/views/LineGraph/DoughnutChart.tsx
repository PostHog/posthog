import React, { useEffect, useRef } from 'react'
import {
    registerables,
    ActiveElement,
    Chart,
    ChartEvent,
    ChartItem,
    ChartType,
    ChartPluginsOptions,
    PluginOptionsByType,
    ChartTypeRegistry,
    TooltipModel,
    ChartOptions,
    ChartDataset,
} from 'chart.js'
import 'chartjs-adapter-dayjs'
import { areObjectValuesEmpty } from '~/lib/utils'
import { GraphType } from '~/types'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import {
    ensureTooltipElement,
    LineGraphProps,
    onChartClick,
    onChartHover,
} from 'scenes/insights/views/LineGraph/LineGraph'
import CrosshairPlugin, { CrosshairOptions } from 'chartjs-plugin-crosshair'
import { _DeepPartialObject } from 'chart.js/types/utils'
import ReactDOM from 'react-dom'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { lineGraphLogic } from 'scenes/insights/views/LineGraph/lineGraphLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

if (registerables) {
    // required for storybook to work, not found in esbuild
    Chart.register(...registerables)
}
Chart.register(CrosshairPlugin)
Chart.defaults.animation['duration'] = 0

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

export function DoughnutChart({
    datasets: _datasets,
    hiddenLegendKeys,
    labels,
    type,
    onClick,
    ['data-attr']: dataAttr,
    aggregationAxisFormat = 'numeric',
    tooltip: tooltipConfig,
    showPersonsModal = true,
    labelGroupType,
}: LineGraphProps): JSX.Element {
    const isPie = type === GraphType.Pie

    if (!isPie) {
        throw new Error('PieChart must be a pie chart')
    }

    let datasets = _datasets

    const { createTooltipData } = useValues(lineGraphLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { timezone } = useValues(insightLogic)
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
            datasets = datasets.filter((data) => !hiddenLegendKeys?.[data.id])
        }

        const processedDatasets = datasets.map((dataset) => dataset as ChartDataset<'doughnut'>)

        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: 'doughnut',
            data: {
                labels,
                datasets: processedDatasets,
            },
            options: {
                cutout: '90%',
                responsive: true,
                maintainAspectRatio: false,
                hover: {
                    mode: 'index',
                },
                layout: {
                    padding: {
                        top: 8,
                        bottom: 8,
                    },
                },
                onHover(event: ChartEvent, _: ActiveElement[], chart: Chart) {
                    onChartHover(event, chart, onClick)
                },
                onClick: (event: ChartEvent, _: ActiveElement[], chart: Chart) => {
                    onChartClick(event, chart, datasets, onClick)
                },
                plugins: {
                    legend: {
                        display: false,
                    },
                    crosshair: false as CrosshairOptions,
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
                                const seriesData = createTooltipData(
                                    tooltip.dataPoints,
                                    (dp) => dp.datasetIndex >= 0 && dp.datasetIndex < _datasets.length
                                )

                                ReactDOM.render(
                                    <InsightTooltip
                                        date={dataset?.days?.[tooltip.dataPoints?.[0]?.dataIndex]}
                                        timezone={timezone}
                                        seriesData={seriesData}
                                        hideColorCol={!!tooltipConfig?.hideColorCol}
                                        renderCount={
                                            tooltipConfig?.renderCount ||
                                            ((value: number): string => {
                                                const total = dataset.data.reduce((a: number, b: number) => a + b, 0)
                                                const percentageLabel: number = parseFloat(
                                                    ((value / total) * 100).toFixed(1)
                                                )
                                                return `${formatAggregationAxisValue(
                                                    aggregationAxisFormat,
                                                    value
                                                )} (${percentageLabel}%)`
                                            })
                                        }
                                        forceEntitiesAsColumns={false}
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
                } as _DeepPartialObject<PluginOptionsByType<keyof ChartTypeRegistry>> & ChartPluginsOptions,
            } as ChartOptions<'doughnut'>,
        })
        return () => newChart.destroy()
    }, [datasets, hiddenLegendKeys])

    return (
        <div className="absolute w-full h-full" data-attr={dataAttr}>
            <canvas ref={canvasRef} />
        </div>
    )
}
