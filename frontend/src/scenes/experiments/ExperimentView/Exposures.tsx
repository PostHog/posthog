import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconCorrelationAnalysis, IconPencil } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonTable, Spinner } from '@posthog/lemon-ui'

import { Chart, ChartConfiguration } from 'lib/Chart'
import { getSeriesBackgroundColor, getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'

import { ExperimentExposureCriteria } from '~/queries/schema/schema-general'

import { useChartColors } from '../MetricsView/shared/colors'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { getExposureConfigDisplayName } from '../utils'
import { VariantTag } from './components'

function getExposureCriteriaLabel(exposureCriteria: ExperimentExposureCriteria | undefined): string {
    const exposureConfig = exposureCriteria?.exposure_config
    if (!exposureConfig) {
        return 'Default ($feature_flag_called)'
    }

    const displayName = getExposureConfigDisplayName(exposureConfig)
    return `Custom (${displayName})`
}

export function Exposures(): JSX.Element {
    const { experimentId, exposures, exposuresLoading, exposureCriteria, isExperimentDraft } =
        useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(modalsLogic)
    const colors = useChartColors()

    const chartRef = useRef<Chart | null>(null)
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [isCollapsed, setIsCollapsed] = useState(true)

    // Calculate total exposures across all variants

    let totalExposures = 0
    const variants: Array<{ variant: string; count: number; percentage: number }> = []

    if (exposures?.timeseries) {
        for (const series of exposures.timeseries) {
            const count = exposures.total_exposures?.[series.variant] || 0
            totalExposures += Number(count)
        }

        // Calculate percentages for each variant
        for (const series of exposures.timeseries) {
            const count = exposures.total_exposures?.[series.variant] || 0
            variants.push({
                variant: series.variant,
                count: Number(count),
                percentage: totalExposures ? (Number(count) / totalExposures) * 100 : 0,
            })
        }
    }

    const createChart = useCallback(
        (ctx: HTMLCanvasElement) => {
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }

            if (!exposures?.timeseries?.length) {
                return
            }

            let labels = exposures.timeseries[0].days.map((day: string) => dayjs(day).format('MM/DD'))
            let datasets = exposures.timeseries.map((series: Record<string, any>, index: number) => ({
                label: series.variant,
                data: series.exposure_counts,
                borderColor: getSeriesColor(index),
                backgroundColor: getSeriesBackgroundColor(index),
                fill: false,
                tension: 0,
                borderWidth: 2,
                pointRadius: 0,
            }))

            // If only one day, pad with a previous day of zeros
            if (exposures.timeseries[0].days.length === 1) {
                const firstDay = dayjs(exposures.timeseries[0].days[0])
                const previousDay = firstDay.subtract(1, 'day').format('MM/DD')

                labels = [previousDay, ...labels]
                datasets = datasets.map((dataset: Record<string, any>) => ({
                    ...dataset,
                    data: [0, ...dataset.data],
                }))
            }

            const config: ChartConfiguration = {
                type: 'line',
                data: {
                    labels,
                    datasets,
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
                        x: {
                            ticks: {
                                maxTicksLimit: 8,
                                autoSkip: true,
                                maxRotation: 0,
                                minRotation: 0,
                            },
                            grid: {
                                display: true,
                                color: colors.EXPOSURES_AXIS_LINES,
                            },
                        },
                        y: {
                            beginAtZero: true,
                            grid: {
                                display: true,
                                color: colors.EXPOSURES_AXIS_LINES,
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
        },
        [exposures, colors.EXPOSURES_AXIS_LINES]
    )

    const canvasRefCallback = useCallback(
        (node: HTMLCanvasElement | null) => {
            canvasRef.current = node
            if (node && exposures?.timeseries?.length && !isCollapsed) {
                // Small delay to ensure canvas is fully mounted
                setTimeout(() => createChart(node), 50)
            }
        },
        [exposures, createChart, isCollapsed]
    )

    useEffect(() => {
        // Re-create chart when data changes and canvas exists and collapse is open
        if (canvasRef.current && exposures?.timeseries?.length && !isCollapsed) {
            createChart(canvasRef.current)
        }
    }, [exposures, createChart, isCollapsed])

    const handleCollapseChange = useCallback(
        (activeKey: string | null) => {
            const isOpen = activeKey === 'cumulative-exposures'
            setIsCollapsed(!isOpen)

            // If opening and we have data and canvas, create chart
            if (isOpen && canvasRef.current && exposures?.timeseries?.length) {
                setTimeout(() => createChart(canvasRef.current!), 100)
            }
        },
        [exposures, createChart]
    )

    useEffect(() => {
        return () => {
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }
        }
    }, [])

    const headerContent = {
        style: { backgroundColor: 'var(--color-bg-table)' },
        children: (
            <div className="flex items-center gap-3 metric-cell">
                <span>Exposures</span>

                {!isExperimentDraft && (
                    <div
                        className={`flex items-center gap-3 transition-opacity duration-300 ease-in-out ${
                            isCollapsed ? 'opacity-100' : 'opacity-0'
                        }`}
                        style={{
                            visibility: isCollapsed ? 'visible' : 'hidden',
                            pointerEvents: isCollapsed ? 'auto' : 'none',
                        }}
                    >
                        {exposuresLoading ? (
                            <Spinner className="text-lg" />
                        ) : (
                            <>
                                <span>
                                    {totalExposures > 100000
                                        ? humanFriendlyLargeNumber(totalExposures)
                                        : humanFriendlyNumber(totalExposures)}
                                </span>
                                {variants.length > 0 && (
                                    <>
                                        <div className="h-4 w-px bg-border" />
                                        <div className="flex items-center gap-4">
                                            {variants.map(({ variant, percentage }) => (
                                                <div key={variant} className="flex items-center gap-2">
                                                    <div className="metric-cell">
                                                        <VariantTag experimentId={experimentId} variantKey={variant} />
                                                    </div>
                                                    <span className="metric-cell">{percentage.toFixed(1)}%</span>
                                                </div>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </>
                        )}
                    </div>
                )}
            </div>
        ),
    }

    return (
        <LemonCollapse
            onChange={handleCollapseChange}
            panels={[
                {
                    key: 'cumulative-exposures',
                    header: headerContent,
                    content: (
                        <div className="space-y-4 bg-bg-light -m-4 p-4">
                            {/* Chart Section */}
                            {exposuresLoading ? (
                                <div className="relative border rounded h-[200px] flex justify-center items-center">
                                    <Spinner className="text-5xl" />
                                </div>
                            ) : !exposures?.timeseries?.length ? (
                                <div className="relative border rounded h-[200px] flex justify-center items-center">
                                    <div className="text-center">
                                        <IconCorrelationAnalysis className="text-3xl mb-2 text-tertiary" />
                                        <div className="text-md font-semibold leading-tight mb-2">No exposures yet</div>
                                        <p className="text-sm text-center text-balance text-tertiary">
                                            Exposures will appear here once the first participant has been exposed.
                                        </p>
                                        <div className="flex justify-center mt-4">
                                            <LemonButton
                                                icon={<IconPencil fontSize="12" />}
                                                size="xsmall"
                                                className="flex items-center gap-2"
                                                type="secondary"
                                                onClick={() => openExposureCriteriaModal()}
                                            >
                                                Edit exposure criteria
                                            </LemonButton>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="relative h-[200px]">
                                    <canvas ref={canvasRefCallback} />
                                </div>
                            )}

                            {/* Exposure Criteria & Total Exposures Section */}
                            <div>
                                <div className="flex justify-between mb-4">
                                    <div>
                                        <h3 className="card-secondary">Exposure criteria</h3>
                                        <div className="flex items-center gap-2">
                                            <div className="text-sm font-semibold">
                                                {getExposureCriteriaLabel(exposureCriteria)}
                                            </div>
                                            <LemonButton
                                                icon={<IconPencil fontSize="12" />}
                                                size="xsmall"
                                                className="flex items-center gap-2"
                                                type="secondary"
                                                onClick={() => openExposureCriteriaModal()}
                                            />
                                        </div>
                                    </div>
                                </div>
                                {exposures?.timeseries.length > 0 && (
                                    <div>
                                        <h3 className="card-secondary">Total exposures</h3>
                                        <div>
                                            <LemonTable
                                                dataSource={[
                                                    ...(exposures?.timeseries || []),
                                                    // Add total row
                                                    { variant: '__total__', isTotal: true },
                                                ]}
                                                columns={[
                                                    {
                                                        title: 'Variant',
                                                        key: 'variant',
                                                        render: function Variant(_, series) {
                                                            if (series.isTotal) {
                                                                return <span className="font-semibold">Total</span>
                                                            }
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
                                                            if (series.isTotal) {
                                                                return (
                                                                    <span className="font-semibold">
                                                                        {humanFriendlyNumber(totalExposures)}
                                                                    </span>
                                                                )
                                                            }
                                                            return humanFriendlyNumber(
                                                                exposures?.total_exposures[series.variant]
                                                            )
                                                        },
                                                    },
                                                    {
                                                        title: '%',
                                                        key: 'percentage',
                                                        render: function Percentage(_, series) {
                                                            if (series.isTotal) {
                                                                // Calculate sum of all individual percentages
                                                                let totalPercentage = 0
                                                                let total = 0
                                                                if (exposures?.total_exposures) {
                                                                    for (const [_, value] of Object.entries(
                                                                        exposures.total_exposures
                                                                    )) {
                                                                        total += Number(value)
                                                                    }
                                                                    if (total > 0) {
                                                                        for (const [_, count] of Object.entries(
                                                                            exposures.total_exposures
                                                                        )) {
                                                                            totalPercentage +=
                                                                                (Number(count) / total) * 100
                                                                        }
                                                                    }
                                                                }
                                                                return (
                                                                    <span className="font-semibold">
                                                                        {totalPercentage
                                                                            ? `${totalPercentage.toFixed(1)}%`
                                                                            : '-%'}
                                                                    </span>
                                                                )
                                                            }
                                                            let total = 0
                                                            if (exposures?.total_exposures) {
                                                                for (const [_, value] of Object.entries(
                                                                    exposures.total_exposures
                                                                )) {
                                                                    total += Number(value)
                                                                }
                                                            }
                                                            return (
                                                                <span className="font-semibold">
                                                                    {total ? (
                                                                        <>
                                                                            {(
                                                                                (exposures?.total_exposures[
                                                                                    series.variant
                                                                                ] /
                                                                                    total) *
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
                                    </div>
                                )}
                            </div>
                        </div>
                    ),
                },
            ]}
        />
    )
}
