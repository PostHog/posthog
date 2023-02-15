import { useEffect, useMemo, useRef, useState } from 'react'
import { useValues } from 'kea'
import { Chart, ChartItem, TooltipModel } from 'chart.js'
import { range } from 'lib/utils'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { teamLogic } from '../../teamLogic'
import { IngestionWarningSummary } from './ingestionWarningsLogic'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { offset } from '@floating-ui/react'

import './WarningEventsGraph.scss'

export function WarningEventsGraph({ summary }: { summary: IngestionWarningSummary }): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const tooltipRef = useRef<HTMLDivElement | null>(null)
    const { timezone } = useValues(teamLogic)

    const [popoverContent, setPopoverContent] = useState<JSX.Element | null>(null)
    const [popoverOffset, setPopoverOffset] = useState(0)

    const dates = useMemo(
        () =>
            range(0, 30)
                .map((i) => dayjs().subtract(i, 'days').format('D MMM YYYY'))
                .reverse(),
        []
    )
    const data = useMemo(() => {
        const result = new Array(30).fill(0)
        for (const warning of summary.warnings) {
            const date = dayjsUtcToTimezone(warning.timestamp, timezone)
            result[dayjs().diff(date, 'days')] += 1
        }
        return result.reverse()
    }, [summary])

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'bar',
                data: {
                    labels: dates,
                    datasets: [
                        {
                            data,
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
                                setPopoverContent(
                                    <>
                                        {datapoint.label}: {datapoint.formattedValue}
                                    </>
                                )
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
    }, [summary, dates, data])

    return (
        <div className="warning-events-graph">
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
