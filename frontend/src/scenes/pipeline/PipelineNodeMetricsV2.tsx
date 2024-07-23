import { IconCalendar } from '@posthog/icons'
import { LemonSelect, LemonSkeleton, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Chart, ChartDataset, ChartItem } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { humanFriendlyNumber, inStorybookTestRunner } from 'lib/utils'
import { useEffect, useRef } from 'react'

import { pipelineNodeLogic } from './pipelineNodeLogic'
import { pipelineNodeMetricsV2Logic } from './pipelineNodeMetricsV2Logic'
import { PipelineBackend } from './types'

const METRICS_INFO = {
    succeeded: 'Total number of events processed successfully',
    failed: 'Total number of events that had errors during processing',
    filtered: 'Total number of events that were filtered out',
    disabled_temporarily:
        'Total number of events that were skipped due to the destination being temporarily disabled (due to issues such as the destination being down or rate-limited)',
    disabled_permanently:
        'Total number of events that were skipped due to the destination being permanently disabled (due to prolonged issues with the destination)',
}

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
                <AppMetricsTotals />

                <div className="flex items-center gap-2">
                    <h2 className="mb-0">Delivery trends</h2>
                    <div className="flex-1" />
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
                        onChange={(from, to) => setFilters({ after: from || undefined, before: to || undefined })}
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

function AppMetricBigNumber({
    label,
    value,
    tooltip,
}: {
    label: string
    value: number | undefined
    tooltip: JSX.Element | string
}): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <div className="border p-2 rounded bg-bg-light flex-1 flex flex-col gap-2 items-center">
                <div className="uppercase font-bold text-xs">{label.replace(/_/g, ' ')}</div>
                <div className="text-2xl flex-1 mb-2 flex items-center">{humanFriendlyNumber(value ?? 0)}</div>
            </div>
        </Tooltip>
    )
}

function AppMetricsTotals(): JSX.Element {
    const { appMetricsTotals, appMetricsTotalsLoading } = useValues(pipelineNodeMetricsV2Logic)

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2 flex-wrap">
                {Object.entries(METRICS_INFO).map(([key, value]) => (
                    <div key={key} className="flex flex-col h-30 min-w-30 flex-1 max-w-100">
                        {appMetricsTotalsLoading ? (
                            <LemonSkeleton className="h-full w-full" />
                        ) : (
                            <AppMetricBigNumber label={key} value={appMetricsTotals.totals?.[key]} tooltip={value} />
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}

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
            color = getColorVar('danger')
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
