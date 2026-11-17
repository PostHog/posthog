import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    DefaultTooltip,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type TooltipContext,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { hasEnded } from 'products/experiments/frontend/experimentStatus'
import {
    type SampleRatioLine,
    getTotalExposures,
    reportsMismatch,
    sampleRatioLine,
    serverSampleRatioFinding,
} from 'products/experiments/frontend/health/exposureHealth'
import { useHealthFindingReporting } from 'products/experiments/frontend/health/useHealthFindingReporting'

import { experimentLogic } from '../experimentLogic'
import { experimentMetricsLogic } from '../experimentMetricsLogic'
import { isSignificant, isWinning } from '../MetricsView/shared/utils'
import { metricResults, resolveMultipleVariantHandling } from '../utils'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'
import { buildExposureSeries, getExposureCriteriaLabel } from './exposuresTransforms'

// Below this, a load looks like any other; above it, the user has no way to tell a slow query
// from a stuck one, so we start showing elapsed time and a way to retry.
const SLOW_LOAD_THRESHOLD_SECONDS = 20

export const EXPOSURES_HELP =
    "Cumulative unique users exposed to the experiment. A user is counted once at first exposure, not per event. Each metric counts its own exposures and can exclude users whose conversion or retention window hasn't elapsed, so metric results can show fewer."
export const HOLDOUT_HELP = 'Users held out of this experiment and not included in analysis.'
export const WINNER_HELP = 'Rolled out to 100% of users when this experiment ended.'
export const NO_EXPOSURES_TITLE = 'No exposures yet'
export const NO_EXPOSURES_DESCRIPTION = 'Exposures will appear here once the first participant has been exposed.'

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

function ExposuresTooltip({ context }: { context: TooltipContext }): JSX.Element {
    const total = context.seriesData.reduce((sum, { value }) => sum + value, 0)
    return (
        <DefaultTooltip
            {...context}
            labelFormatter={(label) => dayjs(label).format('ddd, MMM D, YYYY')}
            valueFormatter={(value) =>
                total > 0
                    ? `${humanFriendlyNumber(value)} (${((value / total) * 100).toFixed(1)}%)`
                    : humanFriendlyNumber(value)
            }
        />
    )
}

export function ExposuresChart({
    exposures,
    className = 'relative h-[200px] flex flex-col',
}: {
    exposures: ExperimentExposureQueryResponse
    className?: string
}): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const { labels, series } = useMemo(() => buildExposureSeries(exposures.timeseries), [exposures.timeseries])
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({ xAxis: { interval: 'day', timezone }, tooltip: { placement: 'cursor' } }),
        [timezone]
    )

    return (
        <div className={className}>
            <TimeSeriesLineChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                tooltip={(context) => <ExposuresTooltip context={context} />}
            />
        </div>
    )
}

export interface ExposuresCardModel {
    exposures: ExperimentExposureQueryResponse | null
    exposuresLoading: boolean
    exposuresElapsedSeconds: number
    exposuresLoadingSlowly: boolean
    totalExposures: number
    isEnded: boolean
    holdoutName: string | null
    holdoutVariantKey: string | null
    excludedVariants: string[]
    exposureCriteriaLabel: string
    winnerKey: string | null
    winningKeys: Set<string>
    winningTooltip: string
    multipleTreatmentLabel: string
    srmLine: SampleRatioLine | null
    hasSampleRatioTest: boolean
    openExposureCriteria: () => void
    editExposureCriteriaFromEmpty: () => void
    retry: () => void
    variantPercentage: (variant: string) => string | null
}

/** Call once per card: it reports the sample ratio and zero exposure findings. */
export function useExposuresCard(): ExposuresCardModel {
    const {
        exposures,
        exposuresLoading,
        exposureCriteria,
        isExperimentDraft,
        experiment,
        excludedVariants,
        resolvedExposureEvent,
        healthUi,
        isSingleVariantShipped,
        shippedVariantKey,
    } = useValues(experimentLogic)
    const { primaryMetricsResults, primaryMetricsResultsErrors } = useValues(experimentMetricsLogic({ experiment }))
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)
    const { refreshExperimentResults } = useActions(experimentLogic)

    const exposuresElapsedSeconds = useElapsedSeconds(exposuresLoading)
    const totalExposures = getTotalExposures(exposures)
    const isEnded = hasEnded(experiment)

    const leadingMetric = metricResults(experiment)(primaryMetricsResults, primaryMetricsResultsErrors, 'primary')[0]
    const winningKeys = new Set(
        !isEnded && leadingMetric?.result
            ? (leadingMetric.result.variant_results ?? [])
                  .filter((variant) => isSignificant(variant) && isWinning(variant, leadingMetric.metric.goal))
                  .map((variant) => variant.key)
            : []
    )

    const srmLine = sampleRatioLine(exposures, healthUi === 'panel')
    const hasSRM = reportsMismatch(srmLine)

    // The open panel says "No exposures yet" for a draft and after a failed exposure query too.
    // Only a launched experiment with an answer that holds no exposure is the zero-exposure state.
    // The answer holds a series for every configured variant, with zero counts, so only the total tells.
    const hasZeroExposures = !isExperimentDraft && !exposuresLoading && exposures != null && totalExposures === 0

    const srmFinding = healthUi === 'panel' ? serverSampleRatioFinding(exposures) : undefined
    useHealthFindingReporting(
        hasSRM && !isExperimentDraft && !exposuresLoading
            ? srmFinding
                ? {
                      code: 'srm',
                      subcode: srmFinding.subcode ?? undefined,
                      severity: srmFinding.severity,
                      reason: srmFinding.reason ?? undefined,
                  }
                : { code: 'srm' }
            : null,
        !srmFinding
    )
    const { reportActedOn: reportZeroExposuresActedOn } = useHealthFindingReporting(
        hasZeroExposures ? { code: 'zero_exposures' } : null
    )

    return {
        exposures,
        exposuresLoading,
        exposuresElapsedSeconds,
        exposuresLoadingSlowly: exposuresLoading && exposuresElapsedSeconds >= SLOW_LOAD_THRESHOLD_SECONDS,
        totalExposures,
        isEnded,
        holdoutName: experiment.holdout?.name ?? null,
        holdoutVariantKey: experiment.holdout ? `holdout-${experiment.holdout_id}` : null,
        excludedVariants,
        exposureCriteriaLabel: getExposureCriteriaLabel(exposureCriteria, resolvedExposureEvent),
        winnerKey: isEnded && isSingleVariantShipped ? shippedVariantKey : null,
        winningKeys,
        winningTooltip: leadingMetric
            ? `Significantly better than ${leadingMetric.result?.baseline?.key ?? 'the baseline'} on ${
                  leadingMetric.metric.name || 'the first primary metric'
              } so far.`
            : '',
        multipleTreatmentLabel:
            resolveMultipleVariantHandling(exposureCriteria?.multiple_variant_handling) === 'first_seen'
                ? 'using first seen variant'
                : 'excluded from analysis',
        srmLine,
        hasSampleRatioTest: srmLine !== null && exposures?.sample_ratio_mismatch != null,
        openExposureCriteria: () => openExposureCriteriaModal(exposureCriteria),
        editExposureCriteriaFromEmpty: () => {
            reportZeroExposuresActedOn('edit_exposure_criteria')
            openExposureCriteriaModal(exposureCriteria)
        },
        retry: () => refreshExperimentResults(true, 'manual'),
        variantPercentage: (variant) => {
            const counts = exposures?.total_exposures
            if (!counts) {
                return null
            }
            let total = 0
            for (const value of Object.values(counts)) {
                total += Number(value)
            }
            return total ? `${((counts[variant] / total) * 100).toFixed(1)}%` : null
        },
    }
}
