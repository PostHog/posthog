import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconCheckCircle, IconCorrelationAnalysis, IconInfo, IconPencil, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonTable, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'
import {
    LineChart,
    type LineChartConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import { ExperimentExposureCriteria, ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { EXPERIMENT_VARIANT_MULTIPLE } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { getActivationConfig, isDefaultExposureConfig } from '../exposureContract'
import { filterLowMultipleVariant, getExposureConfigDisplayName, resolveMultipleVariantHandling } from '../utils'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'
import { buildExposureSeries } from './exposuresTransforms'
import { VariantTag } from './VariantTag'

const srmFailureTooltipText =
    "The distribution of users across variants doesn't match your configured rollout percentages (p < 0.001). This may indicate issues with randomization or data collection."

// Below this, a load looks like any other; above it, the user has no way to tell a slow query
// from a stuck one, so we start showing elapsed time and a way to retry.
const SLOW_LOAD_THRESHOLD_SECONDS = 20

/** Seconds since `active` last became true, ticking every second, reset to 0 when it goes false. */
function useElapsedSeconds(active: boolean): number {
    const [elapsed, setElapsed] = useState(0)
    const startRef = useRef<number | null>(null)

    useEffect(() => {
        if (!active) {
            startRef.current = null
            setElapsed(0)
            return
        }
        startRef.current = performance.now()
        setElapsed(0)
        const intervalId = setInterval(() => {
            setElapsed(Math.floor((performance.now() - (startRef.current as number)) / 1000))
        }, 1000)
        return () => clearInterval(intervalId)
    }, [active])

    return elapsed
}

interface MicroChartProps {
    exposures: ExperimentExposureQueryResponse
}

const CHART_CONFIG: LineChartConfig = {
    hideXAxis: true,
    hideYAxis: true,
    showGrid: false,
    showCrosshair: false,
    curve: 'monotone',
    margins: { top: 1, right: 0, bottom: 1, left: 0 },
    tooltip: { enabled: false },
}

export function MicroChart({ exposures }: MicroChartProps): JSX.Element | null {
    const theme = useChartTheme()
    const timeseries = exposures?.timeseries
    const { labels, series } = useMemo(() => buildExposureSeries(timeseries ?? []), [timeseries])

    if (!timeseries?.length) {
        return null
    }

    return (
        <div className="inline-flex flex-col w-[60px] h-[20px] pointer-events-none border-b border-r border-primary">
            <LineChart series={series} labels={labels} theme={theme} config={CHART_CONFIG} />
        </div>
    )
}

interface ExposuresChartProps {
    exposures: ExperimentExposureQueryResponse
}

function ExposuresChart({ exposures }: ExposuresChartProps): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const { labels, series } = useMemo(() => buildExposureSeries(exposures.timeseries), [exposures.timeseries])
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({ xAxis: { interval: 'day', timezone }, tooltip: { placement: 'cursor' } }),
        [timezone]
    )

    return (
        <div className="relative h-[200px] flex flex-col">
            <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}

function getExposureCriteriaLabel(
    exposureCriteria: ExperimentExposureCriteria | undefined,
    defaultEvent: string
): string {
    const activationConfig = getActivationConfig(exposureCriteria)
    if (activationConfig) {
        return `Default (${defaultEvent}) + activation (${getExposureConfigDisplayName(activationConfig)})`
    }

    const exposureConfig = exposureCriteria?.exposure_config
    if (!exposureConfig || isDefaultExposureConfig(exposureConfig)) {
        return `Default (${defaultEvent})`
    }

    const displayName = getExposureConfigDisplayName(exposureConfig)
    return `Custom (${displayName})`
}

export function Exposures(): JSX.Element {
    const {
        exposures,
        exposuresLoading,
        exposureCriteria,
        isExperimentDraft,
        experiment,
        excludedVariants,
        resolvedExposureEvent,
    } = useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)
    const { refreshExperimentResults } = useActions(experimentLogic)

    const [isCollapsed, setIsCollapsed] = useState(true)
    const exposuresElapsedSeconds = useElapsedSeconds(exposuresLoading)
    const exposuresLoadingSlowly = exposuresLoading && exposuresElapsedSeconds >= SLOW_LOAD_THRESHOLD_SECONDS

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

    // Collapsed/header: hide `$multiple` below 0.5% for cleanliness
    // Expanded/table: shows `$multiple` for clarity/investigating
    const filteredVariantsForHeader = filterLowMultipleVariant(variants)

    const resolvedHandling = resolveMultipleVariantHandling(exposureCriteria?.multiple_variant_handling)
    const multipleTreatmentLabel =
        resolvedHandling === 'first_seen' ? 'using first seen variant' : 'excluded from analysis'

    // Detect sample ratio mismatch (p < 0.001 is significant)
    const hasSRM = exposures?.sample_ratio_mismatch != null && exposures.sample_ratio_mismatch.p_value < 0.001

    const handleCollapseChange = useCallback((activeKey: string | null) => {
        const isOpen = activeKey === 'cumulative-exposures'
        setIsCollapsed(!isOpen)
    }, [])

    const headerContent = {
        style: { backgroundColor: 'var(--color-bg-table)' },
        children: (
            <div className="flex items-center gap-3 metric-cell" style={{ minHeight: '33px' }}>
                <span className="metric-cell-header font-bold inline-flex items-center gap-1">
                    Exposures
                    <Tooltip title="Cumulative unique users exposed to the experiment. A user is counted once at first exposure, not per event.">
                        <IconInfo className="text-secondary text-base" />
                    </Tooltip>
                </span>

                {!isExperimentDraft && (
                    // Transitioning visibility delays the hidden flip until the fade-out finishes.
                    // The fade-out is shorter so it ends before the 200ms panel slide does; at equal
                    // durations the exit reads as sluggish.
                    <div
                        className={`flex items-center gap-3 transition-[opacity,visibility] ease-in-out ${
                            isCollapsed
                                ? 'visible opacity-100 pointer-events-auto duration-300'
                                : 'invisible opacity-0 pointer-events-none duration-150'
                        }`}
                    >
                        {exposuresLoading ? (
                            <div className="flex items-center gap-2">
                                <Spinner className="text-lg" />
                                {exposuresLoadingSlowly && (
                                    <span className="text-secondary text-xs">
                                        Still loading ({exposuresElapsedSeconds}s)
                                    </span>
                                )}
                            </div>
                        ) : (
                            <>
                                <span>
                                    {totalExposures > 100000
                                        ? humanFriendlyLargeNumber(totalExposures)
                                        : humanFriendlyNumber(totalExposures)}
                                </span>
                                {exposures?.timeseries?.length > 0 && <MicroChart exposures={exposures} />}
                                {filteredVariantsForHeader.length > 0 && (
                                    <div className="ml-2 flex items-center gap-4">
                                        {filteredVariantsForHeader.map(({ variant, percentage }) => (
                                            <div key={variant} className="flex items-center gap-2">
                                                <div className="metric-cell">
                                                    <VariantTag variantKey={variant} />
                                                </div>
                                                <span className="metric-cell">{percentage.toFixed(1)}%</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {hasSRM && (
                                    <Tooltip title={srmFailureTooltipText}>
                                        <IconWarning className="text-warning text-lg" />
                                    </Tooltip>
                                )}
                                {excludedVariants.length > 0 && (
                                    <Tooltip
                                        title={`Excluded from analysis: ${excludedVariants.join(', ')}. Manage on the Variants tab.`}
                                    >
                                        <span className="text-secondary text-xs">
                                            {pluralize(
                                                excludedVariants.length,
                                                'variant excluded',
                                                'variants excluded'
                                            )}
                                        </span>
                                    </Tooltip>
                                )}
                                {experiment.holdout && (
                                    <Tooltip title="Users held out of this experiment and not included in analysis.">
                                        <LemonTag type="option" className="ml-2">
                                            {experiment.holdout.name}
                                        </LemonTag>
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
                                <div className="relative border rounded h-[200px] flex flex-col gap-3 justify-center items-center">
                                    <Spinner className="text-5xl" />
                                    {exposuresLoadingSlowly && (
                                        <div className="flex flex-col items-center gap-2">
                                            <span className="text-secondary text-sm">
                                                Still loading exposures after {exposuresElapsedSeconds}s
                                            </span>
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                onClick={() => refreshExperimentResults(true, 'manual')}
                                            >
                                                Retry
                                            </LemonButton>
                                        </div>
                                    )}
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
                                                onClick={() => openExposureCriteriaModal(exposureCriteria)}
                                            >
                                                Edit exposure criteria
                                            </LemonButton>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <ExposuresChart exposures={exposures} />
                            )}

                            {/* Exposure Criteria Section */}
                            <div className="mb-4">
                                <h3 className="card-secondary">Exposure criteria</h3>
                                <div className="flex items-center gap-2">
                                    <div className="text-sm font-semibold">
                                        {getExposureCriteriaLabel(exposureCriteria, resolvedExposureEvent)}
                                    </div>
                                    <LemonButton
                                        icon={<IconPencil fontSize="12" />}
                                        size="xsmall"
                                        className="flex items-center gap-2"
                                        type="secondary"
                                        onClick={() => openExposureCriteriaModal(exposureCriteria)}
                                    />
                                </div>
                            </div>
                            {(exposures?.timeseries?.length ?? 0) > 0 && (
                                <div>
                                    <h3 className="card-secondary">Total exposures</h3>
                                    <LemonTable
                                        rowClassName={(series) =>
                                            series.isExcluded || series.isHoldout ? 'opacity-60' : ''
                                        }
                                        dataSource={[
                                            //This includes EXPERIMENT_VARIANT_MULTIPLE
                                            ...(exposures?.timeseries || []),
                                            ...excludedVariants.map((variant) => ({
                                                variant,
                                                isExcluded: true,
                                            })),
                                            ...(experiment.holdout
                                                ? [
                                                      {
                                                          variant: `holdout-${experiment.holdout_id}`,
                                                          isHoldout: true,
                                                      },
                                                  ]
                                                : []),
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
                                                    const isMultiple = series.variant === EXPERIMENT_VARIANT_MULTIPLE
                                                    return (
                                                        <div className="flex items-center gap-1.5">
                                                            <VariantTag variantKey={series.variant} />
                                                            {isMultiple && (
                                                                <>
                                                                    <span className="text-xs text-secondary">
                                                                        ({multipleTreatmentLabel})
                                                                    </span>
                                                                    <LemonButton
                                                                        icon={<IconPencil fontSize="12" />}
                                                                        size="xsmall"
                                                                        type="secondary"
                                                                        onClick={() =>
                                                                            openExposureCriteriaModal(exposureCriteria)
                                                                        }
                                                                    />
                                                                </>
                                                            )}
                                                        </div>
                                                    )
                                                },
                                            },
                                            {
                                                title: 'Exposures',
                                                key: 'exposures',
                                                render: function Exposures(
                                                    _,
                                                    { variant, isTotal, isExcluded, isHoldout }
                                                ) {
                                                    if (isTotal) {
                                                        return (
                                                            <span className="font-semibold">
                                                                {humanFriendlyNumber(totalExposures)}
                                                            </span>
                                                        )
                                                    }
                                                    if (isExcluded || isHoldout) {
                                                        return <span className="text-secondary">—</span>
                                                    }
                                                    return humanFriendlyNumber(exposures?.total_exposures[variant])
                                                },
                                            },
                                            {
                                                title: '%',
                                                key: 'percentage',
                                                render: function Percentage(
                                                    _,
                                                    { variant, isTotal, isExcluded, isHoldout }
                                                ) {
                                                    if (isTotal) {
                                                        return (
                                                            <span className="font-semibold">
                                                                {totalExposures > 0 ? '100.0%' : '-%'}
                                                            </span>
                                                        )
                                                    }
                                                    if (isExcluded) {
                                                        return (
                                                            <span className="text-secondary italic">
                                                                Excluded from analysis
                                                            </span>
                                                        )
                                                    }
                                                    if (isHoldout) {
                                                        return (
                                                            <span className="text-secondary italic">
                                                                Reserved (holdout)
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
                                                                        (exposures?.total_exposures[variant] / total) *
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
                                    {exposures?.sample_ratio_mismatch != null && (
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
                                                        (p = {exposures.sample_ratio_mismatch.p_value.toExponential(2)})
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
