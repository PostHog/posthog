import { IconCorrelationAnalysis, IconInfo } from '@posthog/icons'
import { LemonTable, Spinner, Tooltip } from '@posthog/lemon-ui'
import { Chart, ChartConfiguration } from 'chart.js/auto'
import clsx from 'clsx'
import { useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect, useRef } from 'react'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'
import { ExposureCriteriaButton } from './ExposureCriteria'

export function Exposures(): JSX.Element {
    const { experimentId, exposures, exposuresLoading, exposureCriteriaLabel } = useValues(experimentLogic)

    const chartRef = useRef<Chart | null>(null)

    useEffect(() => {
        if (chartRef.current) {
            chartRef.current.destroy()
            chartRef.current = null
        }

        if (!exposures || !exposures?.timeseries?.length) {
            return
        }

        const ctx = document.getElementById('exposuresChart') as HTMLCanvasElement
        if (!ctx) {
            return
        }

        const config: ChartConfiguration = {
            type: 'line',
            data: {
                labels: exposures.timeseries[0].days,
                datasets: exposures.timeseries.map((series: Record<string, any>) => ({
                    label: series.variant,
                    data: series.exposure_counts,
                    borderColor: 'rgb(17 17 17 / 60%)',
                    backgroundColor: 'rgb(17 17 17 / 40%)',
                    fill: true,
                    tension: 0,
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

        try {
            chartRef.current = new Chart(ctx, config)
        } catch (error) {
            console.error('Error creating chart:', error)
        }

        return () => {
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }
        }
    }, [exposures])

    const chartWrapperClasses = 'relative border rounded bg-white p-4 h-[250px]'

    return (
        <div>
            <div className="flex items-center deprecated-space-x-2 mb-2">
                <h2 className="mb-0 font-semibold text-lg leading-6">Exposures</h2>
                <Tooltip title="Shows the daily cumulative count of unique users exposed to each variant throughout the experiment duration.">
                    <IconInfo className="text-secondary text-lg" />
                </Tooltip>
            </div>
            {exposuresLoading ? (
                <div className={clsx(chartWrapperClasses, 'flex justify-center items-center')}>
                    <Spinner className="text-5xl" />
                </div>
            ) : !exposures?.timeseries?.length ? (
                <div className={clsx(chartWrapperClasses, 'flex justify-center items-center')}>
                    <div className="text-center">
                        <IconCorrelationAnalysis className="text-3xl mb-2 text-tertiary" />
                        <h2 className="text-lg leading-tight">No exposures yet</h2>
                        <p className="text-sm text-center text-balance text-tertiary">
                            Exposures will appear here once the first participant has been exposed.
                        </p>
                        <div className="flex justify-center">
                            <ExposureCriteriaButton />
                        </div>
                    </div>
                </div>
            ) : (
                <div className="flex gap-2">
                    <div className={clsx(chartWrapperClasses, 'w-full md:w-2/3')}>
                        <canvas id="exposuresChart" />
                    </div>
                    <div className="md:w-1/3 border rounded bg-white p-4">
                        <div className="flex justify-between mb-4">
                            <div>
                                <h3 className="card-secondary">Exposure criteria</h3>
                                <div className="text-sm font-semibold">{exposureCriteriaLabel}</div>
                            </div>
                            <div>
                                <ExposureCriteriaButton />
                            </div>
                        </div>
                        {exposures?.timeseries.length > 0 && (
                            <div>
                                <h3 className="card-secondary">Total exposures</h3>
                                <LemonTable
                                    dataSource={exposures?.timeseries || []}
                                    columns={[
                                        {
                                            title: 'Variant',
                                            key: 'variant',
                                            render: function Variant(_, series) {
                                                return (
                                                    <VariantTag
                                                        experimentId={experimentId}
                                                        variantKey={series.variant}
                                                    />
                                                )
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
                                                const total =
                                                    exposures?.total_exposures.test + exposures?.total_exposures.control
                                                return (
                                                    <span className="font-semibold">
                                                        {(
                                                            (exposures?.total_exposures[series.variant] / total) *
                                                            100
                                                        ).toFixed(1)}
                                                        %
                                                    </span>
                                                )
                                            },
                                        },
                                    ]}
                                />
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
