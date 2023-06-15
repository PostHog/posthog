import { useEffect, useRef, useState } from 'react'
import { Chart, ChartItem, TooltipModel } from 'lib/Chart'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { offset } from '@floating-ui/react'

import './TableCellSparkline.scss'

export interface SparklineDataset {
    dates?: string[]
    data: number[]
}

export function TableCellSparkline({ dataset }: { dataset: SparklineDataset }): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const tooltipRef = useRef<HTMLDivElement | null>(null)

    const [popoverContent, setPopoverContent] = useState<JSX.Element | null>(null)
    const [popoverOffset, setPopoverOffset] = useState(0)

    useEffect(() => {
        if (!dataset) {
            return
        }

        let chart: Chart
        if (canvasRef.current) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'bar',
                data: {
                    labels: dataset.dates || dataset.data.map(() => ''),
                    datasets: [
                        {
                            data: dataset.data,
                            minBarLength: 3,
                            hoverBackgroundColor: 'brand-blue',
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
    }, [dataset])

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
