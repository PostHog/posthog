import './TableCellSparkline.scss'

import { offset } from '@floating-ui/react'
import { Chart, ChartItem, TooltipModel } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { useEffect, useRef, useState } from 'react'

export function TableCellSparkline({ labels, data }: { labels?: string[]; data: number[] }): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const tooltipRef = useRef<HTMLDivElement | null>(null)

    const [popoverContent, setPopoverContent] = useState<JSX.Element | null>(null)
    const [popoverOffset, setPopoverOffset] = useState(0)

    useEffect(() => {
        // data should always be provided but React can render this without it,
        // so, fall back to an empty array for safety
        if (data === undefined) {
            return
        }

        let chart: Chart
        if (canvasRef.current) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'bar',
                data: {
                    labels: labels || data.map(() => ''),
                    datasets: [
                        {
                            data: data,
                            minBarLength: 3,
                            hoverBackgroundColor: getColorVar('primary'),
                        },
                    ],
                },
                options: {
                    scales: {
                        x: {
                            display: false,
                        },
                        y: {
                            beginAtZero: true,
                            display: false,
                        },
                    },
                    plugins: {
                        // @ts-expect-error Types of library are out of date
                        crosshair: false,
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            enabled: false, // using external tooltip
                            external({ tooltip }: { chart: Chart; tooltip: TooltipModel<'bar'> }) {
                                if (tooltip.opacity === 0) {
                                    setPopoverContent(null)
                                    return
                                }
                                const datapoint = tooltip.dataPoints[0]
                                const tooltipLabel = datapoint.label ? `${datapoint.label}: ` : ''
                                const tooltipContent = `${tooltipLabel} ${datapoint.formattedValue}`
                                setPopoverContent(<>{tooltipContent}</>)
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
