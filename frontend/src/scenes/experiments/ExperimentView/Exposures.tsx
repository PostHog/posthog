import { IconArchive, IconInfo } from '@posthog/icons'
import { LemonTable, Spinner, Tooltip } from '@posthog/lemon-ui'
import { Chart, ChartConfiguration } from 'chart.js/auto'
import { useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect } from 'react'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function Exposures(): JSX.Element {
    const { experimentId, exposures, exposuresLoading } = useValues(experimentLogic)

    useEffect(() => {
        if (!exposures || !exposures.timeseries.length) {
            return
        }

        const ctx = document.getElementById('exposuresChart') as HTMLCanvasElement
        if (!ctx) {
            console.error('Canvas element not found')
            return
        }

        const existingChart = Chart.getChart(ctx)
        if (existingChart) {
            existingChart.destroy()
        }

        const data = exposures.timeseries

        const config: ChartConfiguration = {
            type: 'line',
            data: {
                labels: data[0].days,
                datasets: data.map((series: Record<string, any>) => ({
                    label: series.variant,
                    data: series.exposure_counts,
                    borderColor: 'rgb(17 17 17 / 60%)',
                    backgroundColor: 'rgb(17 17 17 / 40%)',
                    fill: true,
                    tension: 0.4,
                    stack: 'stack1',
                    borderWidth: 2,
                    pointRadius: 0,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'nearest',
                    axis: 'x',
                },
                scales: {
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        grid: {
                            display: true,
                        },
                    },
                },
                plugins: {
                    legend: {
                        display: false,
                        labels: {
                            boxWidth: 4,
                            boxPadding: 20,
                            pointStyle: 'dash',
                        },
                    },
                    // @ts-expect-error
                    crosshair: false,
                },
            },
        }

        new Chart(ctx, config)
    }, [exposures])

    return (
        <div>
            <div className="flex items-center deprecated-space-x-2 mb-2">
                <h2 className="mb-0 font-semibold text-lg leading-6">Exposures</h2>
                <Tooltip title="Shows the daily cumulative count of unique users exposed to each variant throughout the experiment duration.">
                    <IconInfo className="text-secondary text-lg" />
                </Tooltip>
            </div>
            {exposuresLoading ? (
                <div className="h-[200px] bg-white rounded border flex items-center justify-center">
                    <Spinner className="text-5xl" />
                </div>
            ) : !exposures.timeseries.length ? (
                <div className="h-[200px] bg-white rounded border flex items-center justify-center">
                    <div className="text-center">
                        <IconArchive className="text-3xl mb-2 text-tertiary" />
                        <h2 className="text-lg leading-tight">No exposures yet</h2>
                        <p className="text-sm text-center text-balance text-tertiary mb-0">
                            Exposures will appear here once the first participant has been exposed.
                        </p>
                    </div>
                </div>
            ) : (
                <div className="flex gap-2">
                    <div className="relative h-[200px] border rounded bg-white p-4 w-2/3">
                        <canvas id="exposuresChart" />
                    </div>
                    <LemonTable
                        dataSource={exposures?.timeseries || []}
                        className="w-1/3 h-[200px]"
                        columns={[
                            {
                                title: 'Variant',
                                key: 'variant',
                                render: function Variant(_, series) {
                                    return <VariantTag experimentId={experimentId} variantKey={series.variant} />
                                },
                            },
                            {
                                title: 'Exposures',
                                key: 'exposures',
                                render: function Exposures(_, series) {
                                    return humanFriendlyNumber(exposures?.total_exposures[series.variant])
                                },
                            },
                            {
                                title: '%',
                                key: 'percentage',
                                render: function Percentage(_, series) {
                                    let total = 0
                                    if (exposures?.total_exposures) {
                                        for (const [_, value] of Object.entries(exposures.total_exposures)) {
                                            total += Number(value)
                                        }
                                    }
                                    return (
                                        <span className="font-semibold">
                                            {total ? (
                                                <>
                                                    {(
                                                        (exposures?.total_exposures[series.variant] / total) *
                                                        100
                                                    ).toFixed(1)}
                                                    %
                                                </>
                                            ) : (
                                                <>-%</>
                                            )}
                                        </span>
                                    )
                                },
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
