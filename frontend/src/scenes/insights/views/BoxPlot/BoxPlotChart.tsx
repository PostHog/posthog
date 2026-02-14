import { useValues } from 'kea'

import { getGraphColors, getSeriesColor } from 'lib/colors'
import { useChart } from 'lib/hooks/useChart'
import { insightLogic } from 'scenes/insights/insightLogic'

import { BoxPlotDatum } from '~/queries/schema/schema-general'
import { ChartParams } from '~/types'

import { boxPlotChartLogic } from './boxPlotChartLogic'

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function BoxPlotChart(_props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { boxplotData, labels } = useValues(boxPlotChartLogic(insightProps))

    const colors = getGraphColors()
    const seriesColor = getSeriesColor(0)

    const { canvasRef } = useChart({
        getConfig: () => {
            if (!boxplotData || boxplotData.length === 0) {
                return null
            }

            return {
                type: 'boxplot' as any,
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Distribution',
                            data: boxplotData.map((d: BoxPlotDatum) => ({
                                min: d.min,
                                q1: d.q1,
                                median: d.median,
                                q3: d.q3,
                                max: d.max,
                                mean: d.mean,
                            })),
                            backgroundColor: `${seriesColor}40`,
                            borderColor: seriesColor,
                            borderWidth: 1.5,
                            medianColor: seriesColor,
                            meanBackgroundColor: `${seriesColor}80`,
                            meanBorderColor: seriesColor,
                            meanRadius: 3,
                            outlierBackgroundColor: `${seriesColor}80`,
                            outlierBorderColor: seriesColor,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 0 },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (context: any): string[] => {
                                    const raw = context.raw as BoxPlotDatum
                                    if (!raw) {
                                        return []
                                    }
                                    return [
                                        `Max: ${raw.max.toLocaleString()}`,
                                        `Q3: ${raw.q3.toLocaleString()}`,
                                        `Median: ${raw.median.toLocaleString()}`,
                                        `Mean: ${raw.mean.toLocaleString()}`,
                                        `Q1: ${raw.q1.toLocaleString()}`,
                                        `Min: ${raw.min.toLocaleString()}`,
                                    ]
                                },
                            },
                        },
                        crosshair: false as any,
                        zoom: { zoom: { drag: { enabled: false } } },
                    },
                    scales: {
                        x: {
                            ticks: {
                                color: colors.axisLabel as string,
                                font: { size: 12 },
                            },
                            grid: { display: false },
                        },
                        y: {
                            ticks: {
                                color: colors.axisLabel as string,
                                font: { size: 12 },
                            },
                            grid: {
                                color: colors.axisLine as string,
                                borderColor: colors.axisLine as string,
                            },
                        },
                    },
                },
            } as any
        },
        deps: [boxplotData, labels, seriesColor, colors],
    })

    if (!boxplotData || boxplotData.length === 0) {
        return (
            <div className="flex items-center justify-center h-full text-muted">
                Select a numeric property to visualize its distribution over time
            </div>
        )
    }

    return (
        <div className="TrendsInsight w-full h-full">
            <canvas ref={canvasRef} />
        </div>
    )
}
