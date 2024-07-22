import { IconCalendar } from '@posthog/icons'
import { LemonSelect, SpinnerOverlay } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Chart, ChartDataset, ChartItem } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { inStorybookTestRunner } from 'lib/utils'
import { useEffect, useRef } from 'react'

import { pipelineNodeLogic } from './pipelineNodeLogic'
import { pipelineNodeMetricsV2Logic } from './pipelineNodeMetricsV2Logic'
import { PipelineBackend } from './types'

export function PipelineNodeMetricsV2(): JSX.Element {
    const { node } = useValues(pipelineNodeLogic)

    if (node.backend !== PipelineBackend.HogFunction) {
        return <div>Metrics not available for this node</div>
    }

    const logic = pipelineNodeMetricsV2Logic({ id: node.id })

    const { filters } = useValues(logic)
    const { setFilters } = useActions(logic)

    return (
        <BindLogic logic={pipelineNodeMetricsV2Logic} props={{ id: node.id }}>
            <div className="space-y-4">
                <div className="flex items-center justify-end gap-2">
                    <LemonSelect
                        options={[
                            { label: 'Hourly', value: 'hour' },
                            { label: 'Daily', value: 'day' },
                            { label: 'Weekly', value: 'week' },
                        ]}
                        size="small"
                        value={filters.interval}
                        onChange={(value) => setFilters({ interval: value })}
                    />
                    <DateFilter
                        dateTo={filters.before}
                        dateFrom={filters.after}
                        onChange={(from, to) => setFilters({ after: from, before: to })}
                        allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
                        makeLabel={(key) => (
                            <>
                                <IconCalendar /> {key}
                            </>
                        )}
                    />
                </div>

                <AppMetricsGraph />
            </div>
        </BindLogic>
    )
}

// function MetricsOverview({ metrics, metricsLoading }: MetricsOverviewProps): JSX.Element {
//     if (metricsLoading) {
//         return <LemonSkeleton className="w-20 h-4 mb-2" repeat={4} />
//     }

//     return (
//         <div className="space-y-4">
//             <div className="flex items-start gap-8 flex-wrap">
//                 <div>
//                     <div className="text-muted font-semibold mb-2">
//                         Events Processed successfully
//                         <Tooltip title="Total number of events processed successfully">
//                             <IconInfo />
//                         </Tooltip>
//                     </div>
//                     <div className="text-4xl">{renderNumber(metrics?.totals?.successes)}</div>
//                 </div>
//                 <div>
//                     <div className="text-muted font-semibold mb-2">
//                         Events Failed
//                         <Tooltip title="Total number of events that threw an error during processing">
//                             <IconInfo />
//                         </Tooltip>
//                     </div>
//                     <div className="text-4xl">{renderNumber(metrics?.totals?.failures)}</div>
//                 </div>
//             </div>
//         </div>
//     )
// }

function AppMetricsGraph(): JSX.Element {
    const { appMetrics, appMetricsLoading } = useValues(pipelineNodeMetricsV2Logic)
    const canvasRef = useRef<HTMLCanvasElement | null>(null)

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current && appMetrics && !inStorybookTestRunner()) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: appMetrics.labels,
                    datasets: [
                        ...appMetrics.series.map((series) => ({
                            label: series.name,
                            data: series.values,
                            borderColor: '',
                            ...colorConfig(series.name),
                        })),
                    ],
                },
                options: {
                    scales: {
                        x: {
                            ticks: {
                                maxRotation: 0,
                            },
                            grid: {
                                display: false,
                            },
                        },
                        y: {
                            beginAtZero: true,
                        },
                    },
                    plugins: {
                        // @ts-expect-error Types of library are out of date
                        crosshair: false,
                        legend: {
                            display: false,
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

            return () => {
                chart?.destroy()
            }
        }
    }, [appMetrics])

    return (
        <div className="relative border rounded p-6 bg-bg-light h-[50vh]">
            {appMetricsLoading && <SpinnerOverlay />}
            {!!appMetrics && <canvas ref={canvasRef} />}
        </div>
    )
}

function colorConfig(name: string): Partial<ChartDataset<'line', any>> {
    let color = getColorVar('data-color-1')

    switch (name) {
        case 'succeeded':
            color = getColorVar('data-color-1')
            break
        case 'failed':
            color = getColorVar('data-color-12')
            break
        default:
            color = getColorVar('data-color-2')
            break
    }

    return {
        borderColor: color,
        hoverBorderColor: color,
        hoverBackgroundColor: color,
        backgroundColor: color,
        fill: false,
        borderWidth: 2,
        pointRadius: 0,
    }
}
