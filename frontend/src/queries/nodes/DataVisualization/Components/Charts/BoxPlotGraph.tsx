import { useValues } from 'kea'

import { ChartConfiguration } from 'lib/Chart'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { useChart } from 'lib/hooks/useChart'

import { BoxPlotDataPoint, dataVisualizationLogic } from '../../dataVisualizationLogic'

interface BoxPlotGraphProps {
    className?: string
    boxPlotData: BoxPlotDataPoint[]
}

export function BoxPlotGraph({ className, boxPlotData }: BoxPlotGraphProps): JSX.Element {
    const { chartSettings } = useValues(dataVisualizationLogic)
    const colors = getGraphColors()
    const seriesColor = getSeriesColor(0)

    const { canvasRef } = useChart({
        getConfig: () => {
            if (boxPlotData.length === 0) {
                return null
            }

            const labels = boxPlotData.map((d) => d.label)
            const data = boxPlotData.map((d) => ({
                min: d.min,
                q1: d.q1,
                median: d.median,
                q3: d.q3,
                max: d.max,
                ...(d.mean !== undefined ? { mean: d.mean } : {}),
            }))

            return {
                type: 'boxplot' as const,
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Box plot',
                            data,
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
                        crosshair: {
                            snap: { enabled: true },
                            sync: { enabled: false },
                            zoom: { enabled: false },
                            line: {
                                color: colors.crosshair ?? undefined,
                                width: 1,
                            },
                        },
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
                            type: 'linear',
                            beginAtZero: chartSettings.leftYAxisSettings?.startAtZero ?? false,
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
                plugins: [],
            } as ChartConfiguration<'boxplot'>
        },
        deps: [boxPlotData, colors, seriesColor, chartSettings],
    })

    if (boxPlotData.length === 0) {
        return (
            <div className="flex items-center justify-center h-full text-muted">
                Map all required columns (min, Q1, median, Q3, max) to see the box plot
            </div>
        )
    }

    return (
        <div className={`w-full grow relative overflow-hidden ${className ?? ''}`} data-attr="box-plot-graph">
            <canvas ref={canvasRef} />
        </div>
    )
}
