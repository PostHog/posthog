import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconCheckCircle, IconCorrelationAnalysis, IconPencil, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonTable, Spinner, Tooltip } from '@posthog/lemon-ui'

import { getSeriesBackgroundColor, getSeriesColor } from 'lib/colors'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useChart } from 'lib/hooks/useChart'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'

import {
    ExperimentExposureCriteria,
    ExperimentExposureQueryResponse,
    ExperimentExposureTimeSeries,
} from '~/queries/schema/schema-general'

import { useChartColors } from '../MetricsView/shared/colors'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { getExposureConfigDisplayName } from '../utils'
import { VariantTag } from './components'

const srmFailureTooltipText =
    "The distribution of users across variants doesn't match your configured rollout percentages (p < 0.001). This may indicate issues with randomization or data collection."

interface MicroChartProps {
    exposures: ExperimentExposureQueryResponse
}

interface ChartDataset {
    data: number[]
    borderColor: string
    fill: boolean
    tension: number
    borderWidth: number
    pointRadius: number
    label?: string
    backgroundColor?: string
}

function MicroChart({ exposures }: MicroChartProps): JSX.Element | null {
    const { canvasRef } = useChart({
        getConfig: () => {
            if (!exposures?.timeseries?.length) {
                return null
            }

            const timeseries = exposures.timeseries

            let datasets = timeseries.map((series: ExperimentExposureTimeSeries, index: number) => ({
                data: series.exposure_counts,
                borderColor: getSeriesColor(index),
                fill: false,
                tension: 0.3,
                borderWidth: 1.5,
                pointRadius: 0,
            }))

            if (timeseries[0].days.length === 1) {
                datasets = datasets.map((dataset: ChartDataset) => ({
                    ...dataset,
                    data: [0, ...dataset.data],
                }))
            }

            return {
                type: 'line' as const,
                data: {
                    labels: datasets[0].data.map((_: any, i: number) => i),
                    datasets,
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: {
                        duration: 0,
                    },
                    scales: {
                        x: {
                            display: false,
                            grid: {
                                display: false,
                            },
                        },
                        y: {
                            display: false,
                            beginAtZero: true,
                            grid: {
                                display: false,
                            },
                        },
                    },
                    plugins: {
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            enabled: false,
                        },
                    },
                    elements: {
                        line: {
                            borderJoinStyle: 'round',
                        },
                    },
                },
            }
        },
        deps: [exposures],
    })

    if (!exposures?.timeseries?.length) {
        return null
    }

    return (
        <div
            className="inline-block"
            style={{
                width: '60px',
                height: '20px',
                pointerEvents: 'none',
                borderBottom: '1px solid var(--color-border-primary)',
                borderRight: '1px solid var(--color-border-primary)',
            }}
        >
            <canvas ref={canvasRef} />
        </div>
    )
}

function getExposureCriteriaLabel(exposureCriteria: ExperimentExposureCriteria | undefined): string {
    const exposureConfig = exposureCriteria?.exposure_config
    if (!exposureConfig) {
        return 'Default ($feature_flag_called)'
    }

    const displayName = getExposureConfigDisplayName(exposureConfig)
    return `Custom (${displayName})`
}

export function Exposures(): JSX.Element {
    const { exposures, exposuresLoading, exposureCriteria, isExperimentDraft, featureFlags } =
        useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(modalsLogic)
    const colors = useChartColors()

    const [isCollapsed, setIsCollapsed] = useState(true)

    let totalExposures = 0
    const variants: Array<{ variant: string; count: number; percentage: number }> = []

    if (exposures?.timeseries) {
        for (const series of exposures.timeseries) {
            const count = exposures.total_exposures?.[series.variant] || 0
            totalExposures += Number(count)
        }

        for (const series of exposures.timeseries) {
            const count = exposures.total_exposures?.[series.variant] || 0
            variants.push({
                variant: series.variant,
                count: Number(count),
                percentage: totalExposures ? (Number(count) / totalExposures) * 100 : 0,
            })
        }
    }

    // Detect sample ratio mismatch (p < 0.001 is significant)
    const hasSRM = exposures?.sample_ratio_mismatch != null && exposures.sample_ratio_mismatch.p_value < 0.001

    const { canvasRef } = useChart({
        getConfig: () => {
            if (isCollapsed || !exposures?.timeseries?.length) {
                return null
            }

            let labels = exposures.timeseries[0].days.map((day: string) => dayjs(day).format('MM/DD'))
            let datasets = exposures.timeseries.map((series: ExperimentExposureTimeSeries, index: number) => ({
                label: series.variant,
                data: series.exposure_counts,
                borderColor: getSeriesColor(index),
                backgroundColor: getSeriesBackgroundColor(index),
                fill: false,
                tension: 0,
                borderWidth: 2,
                pointRadius: 0,
            }))

            if (exposures.timeseries[0].days.length === 1) {
                const firstDay = dayjs(exposures.timeseries[0].days[0])
                const previousDay = firstDay.subtract(1, 'day').format('MM/DD')

                labels = [previousDay, ...labels]
                datasets = datasets.map((dataset: ChartDataset) => ({
                    ...dataset,
                    data: [0, ...dataset.data],
                }))
            }

            return {
                type: 'line' as const,
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
                        crosshair: false,
                    },
                },
            }
        },
        deps: [exposures, colors.EXPOSURES_AXIS_LINES, isCollapsed],
    })

    const handleCollapseChange = useCallback((activeKey: string | null) => {
        const isOpen = activeKey === 'cumulative-exposures'
        setIsCollapsed(!isOpen)
    }, [])

    const headerContent = {
        style: { backgroundColor: 'var(--color-bg-table)' },
        children: (
            <div className="flex items-center gap-3 metric-cell" style={{ minHeight: '33px' }}>
                <span className="metric-cell-header font-bold">Exposures</span>

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
                                {exposures?.timeseries?.length > 0 && <MicroChart exposures={exposures} />}
                                {variants.length > 0 && (
                                    <div className="ml-2 flex items-center gap-4">
                                        {variants.map(({ variant, percentage }) => (
                                            <div key={variant} className="flex items-center gap-2">
                                                <div className="metric-cell">
                                                    <VariantTag variantKey={variant} />
                                                </div>
                                                <span className="metric-cell">{percentage.toFixed(1)}%</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {featureFlags[FEATURE_FLAGS.EXPERIMENTS_SAMPLE_RATIO_MISMATCH] && hasSRM && (
                                    <Tooltip title={srmFailureTooltipText}>
                                        <IconWarning className="text-warning text-lg" />
                                    </Tooltip>
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
                                    <canvas ref={canvasRef} />
                                </div>
                            )}

                            {/* Exposure Criteria Section */}
                            <div className="mb-4">
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
                            {exposures?.timeseries.length > 0 && (
                                <div>
                                    <h3 className="card-secondary">Total exposures</h3>
                                    <LemonTable
                                        dataSource={[
                                            ...(exposures?.timeseries || []),
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
                                                    return <VariantTag variantKey={series.variant} />
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
                                                                    totalPercentage += (Number(count) / total) * 100
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
                                                                        (exposures?.total_exposures[series.variant] /
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
                                    {featureFlags[FEATURE_FLAGS.EXPERIMENTS_SAMPLE_RATIO_MISMATCH] &&
                                        exposures?.sample_ratio_mismatch != null && (
                                            <div className="flex items-center gap-1 text-xs mt-2">
                                                {hasSRM ? (
                                                    <>
                                                        <Tooltip title={srmFailureTooltipText}>
                                                            <span className="flex items-center gap-1 text-warning cursor-pointer">
                                                                <IconWarning className="text-sm" />
                                                                <span className="font-semibold">
                                                                    Sample ratio mismatch detected
                                                                </span>
                                                            </span>
                                                        </Tooltip>
                                                        <span className="text-muted">
                                                            (p ={' '}
                                                            {exposures.sample_ratio_mismatch.p_value.toExponential(2)})
                                                        </span>
                                                    </>
                                                ) : (
                                                    <>
                                                        <Tooltip title="No sample ratio mismatch detected. The difference between actual and expected exposures is within normal random variation.">
                                                            <span className="flex items-center gap-1 text-success cursor-pointer">
                                                                <IconCheckCircle className="text-sm" />
                                                                <span>
                                                                    Exposure distribution matches rollout percentages
                                                                </span>
                                                            </span>
                                                        </Tooltip>
                                                        <span className="text-muted">
                                                            (p = {exposures.sample_ratio_mismatch.p_value.toFixed(3)})
                                                        </span>
                                                    </>
                                                )}
                                            </div>
                                        )}
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
