import './TableCellSparkline.scss'

import { offset } from '@floating-ui/react'
import { Chart, ChartItem, TooltipModel } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import React from 'react'
import { useEffect, useRef, useState } from 'react'

export interface SparkLineTimeSeries {
    name: string | null // used in the tooltip
    color: string // check vars.css for available colors
    values: number[]
}

function isSparkLineTimeSeries(data: number[] | SparkLineTimeSeries[]): data is SparkLineTimeSeries[] {
    return typeof data[0] !== 'number'
}

// @param labels - optional labels for the x-axis
// @param data - either a list of numbers for a gray graph or an array of multiple timerseries
export function TableCellSparkline({
    labels,
    data,
}: {
    labels?: string[]
    data: number[] | SparkLineTimeSeries[]
}): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const tooltipRef = useRef<HTMLDivElement | null>(null)

    const [popoverContent, setPopoverContent] = useState<JSX.Element | null>(null)
    const [popoverOffset, setPopoverOffset] = useState(0)

    useEffect(() => {
        // data should always be provided but React can render this without it,
        // so, fall back to an empty array for safety
        if (data === undefined || data.length === 0) {
            return
        }

        const adjustedData: SparkLineTimeSeries[] = !isSparkLineTimeSeries(data)
            ? [{ name: null, color: 'muted', values: data }]
            : data

        let chart: Chart
        if (canvasRef.current) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'bar',
                data: {
                    labels: labels || Object.values(adjustedData).map(() => ''),
                    datasets: adjustedData.map((timeseries) => ({
                        data: timeseries.values,
                        minBarLength: 0,
                        backgroundColor: getColorVar(timeseries.color),
                        hoverBackgroundColor: getColorVar('primary'),
                    })),
                },
                options: {
                    scales: {
                        x: {
                            display: false,
                            stacked: true,
                        },
                        y: {
                            beginAtZero: true,
                            display: false,
                            stacked: true,
                        },
                    },
                    plugins: {
                        // @ts-expect-error Types of library are out of date
                        crosshair: false,
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            // TODO: use InsightsTooltip instead
                            enabled: false, // using external tooltip
                            external({ tooltip }: { chart: Chart; tooltip: TooltipModel<'bar'> }) {
                                if (tooltip.opacity === 0) {
                                    setPopoverContent(null)
                                    return
                                }
                                const datapoint = tooltip.dataPoints[0]
                                const toolTipLabel = datapoint.label ? `${datapoint.label}: ` : ''
                                if (tooltip.dataPoints.length === 1) {
                                    const tooltipContent = toolTipLabel + datapoint.formattedValue
                                    setPopoverContent(<>{tooltipContent}</>)
                                } else {
                                    const tooltipContent = [<React.Fragment key="-1">{toolTipLabel}</React.Fragment>]
                                    for (let i = 0; i < tooltip.dataPoints.length; i++) {
                                        const datapoint = tooltip.dataPoints[i]
                                        tooltipContent.push(
                                            <React.Fragment key={i}>
                                                <br />
                                                {adjustedData[i].name}: {datapoint.formattedValue}
                                            </React.Fragment>
                                        )
                                    }
                                    setPopoverContent(<>{tooltipContent}</>)
                                }
                                setPopoverOffset(tooltip.x)
                            },
                        },
                    },
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        axis: 'x',
                        intersect: false,
                    },
                },
            })
        }
        return () => {
            chart?.destroy()
        }
    }, [labels, data])

    return (
        <div className="TableCellSparkline">
            <canvas ref={canvasRef} />
            <Popover
                visible={!!popoverContent}
                overlay={popoverContent}
                placement="bottom-start"
                middleware={[offset({ crossAxis: popoverOffset })]}
            >
                <div ref={tooltipRef} />
            </Popover>
        </div>
    )
}
