import 'chartjs-adapter-dayjs-3'
import ChartDataLabels, { Context } from 'chartjs-plugin-datalabels'
import { useActions, useValues } from 'kea'

import {
    ActiveElement,
    Chart,
    ChartDataset,
    ChartEvent,
    ChartOptions,
    ChartType,
    Plugin,
    TooltipModel,
} from 'lib/Chart'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { useChart } from 'lib/hooks/useChart'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'
import { LineGraphProps, onChartClick, onChartHover } from 'scenes/insights/views/LineGraph/LineGraph'
import { createTooltipData } from 'scenes/insights/views/LineGraph/tooltip-data'
import { IndexedTrendResult } from 'scenes/trends/types'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { GraphType } from '~/types'

function getPercentageForDataPoint(context: Context): number {
    const total = context.dataset.data.reduce((a, b) => (a as number) + (b as number), 0) as number
    return ((context.dataset.data[context.dataIndex] as number) / total) * 100
}

export interface PieChartProps extends LineGraphProps {
    breakdownFilter?: BreakdownFilter | null | undefined
    showLabelOnSeries?: boolean | null
    disableHoverOffset?: boolean | null
}

export function PieChart({
    datasets: _datasets,
    labels,
    type,
    onClick,
    ['data-attr']: dataAttr,
    trendsFilter,
    breakdownFilter,
    formula,
    showValuesOnSeries,
    showLabelOnSeries,
    supportsPercentStackView,
    showPercentStackView,
    tooltip: tooltipConfig,
    showPersonsModal = true,
    labelGroupType,
    disableHoverOffset,
}: PieChartProps): JSX.Element {
    const isPie = type === GraphType.Pie
    const isPercentStackView = !!supportsPercentStackView && !!showPercentStackView

    if (!isPie) {
        throw new Error('PieChart must be a pie chart')
    }

    const datasets = _datasets

    const { aggregationLabel } = useValues(groupsModel)
    const { highlightSeries } = useActions(insightLogic)
    const { getTooltip, hideTooltip } = useInsightTooltip()

    const { canvasRef } = useChart<'pie'>({
        getConfig: () => {
            const processedDatasets = datasets.map((dataset) => dataset as ChartDataset<'pie'>)
            const onlyOneValue = processedDatasets?.[0]?.data?.length === 1

            return {
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
                            top: 12,
                            left: 20,
                            right: 20,
                            bottom: 20,
                        },
                    },
                    borderWidth: 0,
                    borderRadius: 0,
                    hoverOffset: onlyOneValue || disableHoverOffset ? 0 : 16,
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
                                const showValueForSeries =
                                    showValuesOnSeries !== false && context.dataset.data.length > 1
                                return (showValueForSeries || showLabelOnSeries) && percentage > 5 ? 'auto' : false
                            },
                            padding: (context) => {
                                const value = context.dataset.data[context.dataIndex] as number
                                const paddingY = value < 10 ? 2 : 4
                                const paddingX = value < 10 ? 5 : 4
                                return { top: paddingY, bottom: paddingY, left: paddingX, right: paddingX }
                            },
                            formatter: (value: number, context) => {
                                if (showLabelOnSeries) {
                                    return (context.dataset as any).labels?.[context.dataIndex]
                                }
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
                            external: function ({
                                chart,
                                tooltip,
                            }: {
                                chart: Chart
                                tooltip: TooltipModel<ChartType>
                            }) {
                                const [tooltipRoot, tooltipEl] = getTooltip()
                                if (tooltip.opacity === 0) {
                                    if (trendsFilter?.showLegend) {
                                        highlightSeries(null)
                                    }
                                    hideTooltip()
                                    return
                                }

                                tooltipEl.classList.remove('above', 'below', 'no-transform', 'opacity-0', 'invisible')
                                tooltipEl.classList.add(tooltip.yAlign || 'no-transform')
                                tooltipEl.style.opacity = '1'

                                if (tooltip.body) {
                                    const referenceDataPoint = tooltip.dataPoints[0]
                                    const dataset = datasets[referenceDataPoint.datasetIndex]
                                    const seriesData = createTooltipData(
                                        tooltip.dataPoints,
                                        (dp) => dp.datasetIndex >= 0 && dp.datasetIndex < _datasets.length
                                    )

                                    highlightSeries(seriesData[0] as unknown as IndexedTrendResult)

                                    tooltipRoot.render(
                                        <InsightTooltip
                                            seriesData={seriesData}
                                            breakdownFilter={breakdownFilter}
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
                                                    const total = dataset.data.reduce(
                                                        (a: number, b: number) => a + b,
                                                        0
                                                    )
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
                                        />
                                    )
                                }

                                const position = chart.canvas.getBoundingClientRect()
                                tooltipEl.style.position = 'absolute'
                                tooltipEl.style.left =
                                    position.left + window.pageXOffset + (tooltip.caretX || 0) + 8 + 'px'
                                tooltipEl.style.top =
                                    position.top + window.pageYOffset + (tooltip.caretY || 0) + 8 + 'px'
                            },
                        },
                    },
                } as ChartOptions<'pie'>,
            }
        },
        deps: [
            datasets,
            labels,
            onClick,
            trendsFilter,
            breakdownFilter,
            formula,
            showValuesOnSeries,
            showLabelOnSeries,
            isPercentStackView,
            tooltipConfig,
            showPersonsModal,
            labelGroupType,
            disableHoverOffset,
            getTooltip,
            hideTooltip,
            highlightSeries,
            aggregationLabel,
        ],
    })

    return (
        <div className="absolute w-full h-full" data-attr={dataAttr}>
            <canvas ref={canvasRef} />
        </div>
    )
}
