import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonDivider, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'

import {
    ExperimentTrendsQuery,
    ExperimentFunnelsQuery,
    CachedExperimentTrendsQueryResponse,
    CachedExperimentFunnelsQueryResponse,
    CachedLegacyExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { DEFAULT_MDE } from '~/scenes/experiments/experimentLogic'
import { legacyExperimentLogic, getInsightType } from '~/scenes/experiments/legacy'
import { formatUnitByQuantity } from '~/scenes/experiments/utils'
import { Experiment, InsightType } from '~/types'

const getFirstPrimaryMetric = (experiment: Experiment): ExperimentTrendsQuery | ExperimentFunnelsQuery | null => {
    if (experiment.metrics.length) {
        return experiment.metrics[0] as ExperimentTrendsQuery | ExperimentFunnelsQuery
    }
    const primaryMetric = experiment.saved_metrics.find((metric) => metric.metadata.type === 'primary')
    if (primaryMetric) {
        return primaryMetric.query as ExperimentTrendsQuery | ExperimentFunnelsQuery
    }
    return null
}

const getActualRunningTime = (experiment: Experiment): number => {
    if (!experiment.start_date) {
        return 0
    }

    if (experiment.end_date) {
        return dayjs(experiment.end_date).diff(experiment.start_date, 'day')
    }

    return dayjs().diff(experiment.start_date, 'day')
}

const getFunnelResultsPersonsTotal =
    (
        experiment: Experiment,
        legacyPrimaryMetricsResults: (
            | CachedLegacyExperimentQueryResponse
            | CachedExperimentFunnelsQueryResponse
            | CachedExperimentTrendsQueryResponse
            | null
        )[],
        getInsightType: (metric: ExperimentTrendsQuery | ExperimentFunnelsQuery) => InsightType
    ) =>
    (metricIdentifier: number | string = 0): number => {
        let index: number
        if (typeof metricIdentifier === 'string') {
            // Find index by UUID
            index = experiment.metrics.findIndex((m) => m.uuid === metricIdentifier)
            if (index === -1) {
                return 0
            }
        } else {
            index = metricIdentifier
        }

        const result = legacyPrimaryMetricsResults?.[index]

        if (
            getInsightType(experiment.metrics[index] as ExperimentTrendsQuery | ExperimentFunnelsQuery) !==
                InsightType.FUNNELS ||
            !result
        ) {
            return 0
        }

        let sum = 0
        result.insight.forEach((variantResult) => {
            if (variantResult[0]?.count) {
                sum += variantResult[0].count
            }
        })
        return sum
    }

/**
 * @deprecated
 * Legacy goal tooltip for ExperimentView.
 * Frozen copy for legacy experiments - do not modify.
 */
function LegacyGoalTooltip({
    experiment,
    hasHighRunningTime,
}: {
    experiment: Experiment | null
    hasHighRunningTime: boolean
}): JSX.Element {
    if (!experiment?.parameters?.minimum_detectable_effect) {
        return <></>
    }

    return (
        <Tooltip
            title={
                <div>
                    <div>{`Based on the Minimum detectable effect of ${experiment.parameters.minimum_detectable_effect}%.`}</div>
                    {hasHighRunningTime && (
                        <div className="mt-2">
                            Given the current data, this experiment might take a while to reach statistical
                            significance. Please make sure events are being tracked correctly and consider if this
                            timeline works for you.
                        </div>
                    )}
                </div>
            }
        >
            <IconInfo className="text-secondary text-base" />
        </Tooltip>
    )
}

/**
 * @deprecated
 * Legacy data collection component for ExperimentView.
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyDataCollection(): JSX.Element {
    const { experiment, legacyPrimaryMetricsResults } = useValues(legacyExperimentLogic)

    /**
     * these variables were computed in the experimentLogic.
     * the legacy experiment logic does not have these computed values.
     */
    const firstPrimaryMetric = getFirstPrimaryMetric(experiment)
    const insightType = firstPrimaryMetric ? getInsightType(firstPrimaryMetric) : InsightType.FUNNELS
    const actualRunningTime = getActualRunningTime(experiment)
    const minimumDetectableEffect = experiment?.parameters?.minimum_detectable_effect || DEFAULT_MDE
    const funnelResultsPersonsTotal = getFunnelResultsPersonsTotal(
        experiment,
        legacyPrimaryMetricsResults,
        getInsightType
    )

    const recommendedRunningTime = experiment?.parameters?.recommended_running_time || 1
    const recommendedSampleSize = experiment?.parameters?.recommended_sample_size || 100

    const experimentProgressPercent =
        insightType === InsightType.FUNNELS
            ? (funnelResultsPersonsTotal(0) / recommendedSampleSize) * 100
            : (actualRunningTime / recommendedRunningTime) * 100

    const hasHighRunningTime = recommendedRunningTime > 62

    return (
        <div>
            <div className="inline-flex items-center deprecated-space-x-2">
                <h2 className="font-semibold text-lg mb-0">Data collection</h2>
                <Tooltip
                    title="Estimated target for the number of participants. Actual data may reveal significance earlier or later
                    than predicted."
                >
                    <IconInfo className="text-secondary text-base" />
                </Tooltip>
            </div>
            <div className="flex">
                <div className="w-3/5 pr-4">
                    <div className="mt-2 mb-1 font-semibold">{`${
                        experimentProgressPercent > 100 ? 100 : experimentProgressPercent.toFixed(2)
                    }% complete`}</div>
                    <LemonProgress
                        className="w-full border"
                        bgColor="var(--color-bg-table)"
                        size="medium"
                        percent={experimentProgressPercent}
                    />
                    {insightType === InsightType.TRENDS && (
                        <div className="flex justify-between mt-0">
                            <span className="flex items-center text-xs">
                                Completed&nbsp;
                                <b>{actualRunningTime} of</b>
                                {hasHighRunningTime ? (
                                    <b>&nbsp; &gt; 60 days</b>
                                ) : (
                                    <span>
                                        &nbsp;
                                        <b>{recommendedRunningTime}</b>{' '}
                                        {formatUnitByQuantity(recommendedRunningTime, 'day')}
                                    </span>
                                )}
                                <span className="ml-1 text-xs">
                                    <LegacyGoalTooltip
                                        experiment={experiment}
                                        hasHighRunningTime={hasHighRunningTime}
                                    />
                                </span>
                            </span>
                        </div>
                    )}
                    {insightType === InsightType.FUNNELS && (
                        <div className="flex justify-between mt-0">
                            <div className="deprecated-space-x-1 flex items-center text-xs">
                                <span>
                                    Saw&nbsp;
                                    <b>
                                        {humanFriendlyNumber(funnelResultsPersonsTotal(0))} of{' '}
                                        {humanFriendlyNumber(recommendedSampleSize)}{' '}
                                    </b>{' '}
                                    {formatUnitByQuantity(recommendedSampleSize, 'participant')}
                                </span>
                                <LegacyGoalTooltip experiment={experiment} hasHighRunningTime={hasHighRunningTime} />
                            </div>
                        </div>
                    )}
                </div>
                <LemonDivider className="my-0" vertical />
                <div className="w-2/5 pl-4">
                    <div className={`text-lg font-semibold ${experiment.end_date ? 'mt-4' : ''}`}>
                        {minimumDetectableEffect}%
                    </div>
                    <div className="deprecated-space-x-1 text-sm flex">
                        <span>Minimum detectable effect</span>
                        <Tooltip
                            title={
                                <div className="deprecated-space-y-2">
                                    <div>
                                        The Minimum detectable effect represents the smallest change that you want to be
                                        able to detect in your experiment.
                                    </div>
                                    <div>
                                        To make things easier, we initially set this value to a reasonable default.
                                        However, we encourage you to review and adjust it based on your specific goals.
                                    </div>
                                    <div>
                                        Read more in the{' '}
                                        <Link to="https://posthog.com/docs/experiments/sample-size-running-time#minimum-detectable-effect-mde">
                                            documentation.
                                        </Link>
                                    </div>
                                </div>
                            }
                            closeDelayMs={200}
                        >
                            <IconInfo className="text-secondary text-base" />
                        </Tooltip>
                    </div>
                </div>
            </div>
        </div>
    )
}
