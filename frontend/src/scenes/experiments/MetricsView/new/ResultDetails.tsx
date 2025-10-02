import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils'
import { FunnelChart } from 'scenes/experiments/charts/funnel/FunnelChart'
import { ResultsBreakdown } from 'scenes/experiments/components/ResultsBreakdown/ResultsBreakdown'
import { ResultsBreakdownSkeleton } from 'scenes/experiments/components/ResultsBreakdown/ResultsBreakdownSkeleton'
import { ResultsInsightInfoBanner } from 'scenes/experiments/components/ResultsBreakdown/ResultsInsightInfoBanner'
import { ResultsQuery } from 'scenes/experiments/components/ResultsBreakdown/ResultsQuery'
import { getViewRecordingFilters } from 'scenes/experiments/utils'
import { urls } from 'scenes/urls'

import {
    CachedNewExperimentQueryResponse,
    ExperimentMetric,
    NodeKind,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import {
    EntityType,
    Experiment,
    FilterLogicalOperator,
    FunnelStep,
    FunnelStepWithNestedBreakdown,
    RecordingUniversalFilters,
    ReplayTabs,
} from '~/types'

import {
    ExperimentVariantResult,
    formatChanceToWin,
    formatMetricValue,
    formatPValue,
    getIntervalLabel,
    getVariantInterval,
    isBayesianResult,
    isFrequentistResult,
} from '../shared/utils'

/**
 * Convert new experiment results directly to DataDrivenFunnel format
 */
function convertExperimentResultToFunnelSteps(
    result: CachedNewExperimentQueryResponse,
    metric: ExperimentMetric
): FunnelStepWithNestedBreakdown[] {
    const allResults = [result.baseline, ...(result.variant_results || [])]
    const numSteps = (result.baseline.step_counts?.length || 0) + 1
    const funnelSteps: FunnelStepWithNestedBreakdown[] = []

    for (let stepIndex = 0; stepIndex < numSteps; stepIndex++) {
        const variantSteps: FunnelStep[] = allResults.map((variantResult, variantIndex) => {
            let count: number
            if (stepIndex === 0) {
                count = variantResult.number_of_samples
            } else {
                count = variantResult.step_counts?.[stepIndex - 1] || 0
            }

            let stepName: string
            if (stepIndex === 0) {
                stepName = 'Experiment exposure'
            } else if (isExperimentFunnelMetric(metric) && metric.series?.[stepIndex - 1]) {
                const series = metric.series[stepIndex - 1]
                if (series.kind === NodeKind.EventsNode) {
                    stepName = series.name || series.event || `Step ${stepIndex}`
                } else {
                    stepName = series.name || `Action ${series.id}`
                }
            } else {
                stepName = `Step ${stepIndex}`
            }

            return {
                name: stepName,
                custom_name: null,
                count: count,
                type: 'events' as EntityType,
                breakdown_value: variantResult.key,
                breakdown_index: variantIndex,
            } as FunnelStep & { breakdown_index: number }
        })

        const baseStep = variantSteps[0]
        const totalCount = variantSteps.reduce((sum, step) => sum + step.count, 0)

        funnelSteps.push({
            ...baseStep,
            count: totalCount,
            nested_breakdown: variantSteps,
        })
    }

    return funnelSteps
}

export function ResultDetails({
    experiment,
    result,
    metric,
    isSecondary,
}: {
    experiment: Experiment
    result: CachedNewExperimentQueryResponse
    metric: ExperimentMetric
    isSecondary: boolean
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    // If feature flag is enabled _and_ the result contains the step_counts data, we use the new funnel chart
    const useExperimentFunnelChart =
        featureFlags[FEATURE_FLAGS.EXPERIMENTS_FUNNEL_CHART] === 'test' && result.baseline.step_counts !== undefined

    const columns: LemonTableColumns<ExperimentVariantResult & { key: string }> = [
        {
            key: 'variant',
            title: 'Variant',
            render: (_, item) => <div className="font-semibold">{item.key}</div>,
        },
        {
            key: 'total-users',
            title: 'Total users',
            render: (_, item) => humanFriendlyNumber(item.number_of_samples),
        },
        {
            key: 'value',
            title: isExperimentMeanMetric(metric)
                ? 'Mean'
                : isExperimentRatioMetric(metric)
                  ? 'Ratio'
                  : 'Conversion rate',
            render: (_, item) => formatMetricValue(item, metric),
        },
        {
            key: 'statistical_measure',
            title:
                result.variant_results?.[0] && isBayesianResult(result.variant_results[0])
                    ? 'Chance to win'
                    : 'p-value',
            render: (_, item: ExperimentVariantResult & { key: string }) => {
                if (item.key === 'control') {
                    return '—'
                }

                if (isBayesianResult(item)) {
                    return <div className="font-semibold">{formatChanceToWin(item.chance_to_win)}</div>
                } else if (isFrequentistResult(item)) {
                    return <div className="font-semibold">{formatPValue(item.p_value)}</div>
                }
                return '—'
            },
        },
        {
            key: 'significant',
            title: 'Significant',
            render: (_, item: ExperimentVariantResult & { key: string }) => {
                if (item.key === 'control') {
                    return '—'
                }
                if (!('significant' in item)) {
                    return '—'
                }
                const label = item.significant ? 'Yes' : 'No'
                return item.significant ? <div className="text-success font-semibold">{label}</div> : label
            },
        },
        {
            key: 'interval',
            title: result.variant_results?.[0]
                ? `${getIntervalLabel(result.variant_results[0])} (95%)`
                : 'Confidence interval (95%)',
            render: (_, item: ExperimentVariantResult & { key: string }) => {
                if (item.key === 'control') {
                    return '—'
                }
                const interval = getVariantInterval(item)
                if (!interval) {
                    return '—'
                }
                return `[${(interval[0] * 100).toFixed(2)}%, ${(interval[1] * 100).toFixed(2)}%]`
            },
        },
        {
            key: 'recordings',
            title: '',
            render: (_, item) => {
                const variantKey = item.key
                const filters = getViewRecordingFilters(experiment, metric, variantKey)

                return (
                    <LemonButton
                        size="xsmall"
                        icon={<IconRewindPlay />}
                        tooltip="Watch recordings of people who were exposed to this variant."
                        disabledReason={
                            filters.length === 0 ? 'Unable to identify recordings for this metric' : undefined
                        }
                        type="secondary"
                        onClick={() => {
                            const filterGroup: Partial<RecordingUniversalFilters> = {
                                filter_group: {
                                    type: FilterLogicalOperator.And,
                                    values: [
                                        {
                                            type: FilterLogicalOperator.And,
                                            values: filters,
                                        },
                                    ],
                                },
                                date_from: experiment?.start_date,
                                date_to: experiment?.end_date,
                                filter_test_accounts: experiment.exposure_criteria?.filterTestAccounts ?? false,
                            }
                            router.actions.push(urls.replay(ReplayTabs.Home, filterGroup))
                            posthog.capture('viewed recordings from experiment', { variant: variantKey })
                        }}
                    >
                        View recordings
                    </LemonButton>
                )
            },
        },
    ]

    const dataSource = [
        ...(result.baseline
            ? [{ ...result.baseline, key: 'control' } as ExperimentVariantResult & { key: string }]
            : []),
        ...(result.variant_results || []),
    ]

    return (
        <div className="space-y-2">
            <LemonTable columns={columns} dataSource={dataSource} loading={false} />
            {isExperimentFunnelMetric(metric) &&
                (useExperimentFunnelChart ? (
                    <FunnelChart
                        steps={convertExperimentResultToFunnelSteps(result, metric)}
                        showPersonsModal={false}
                        disableBaseline={true}
                        inCardView={true}
                        experimentResult={result}
                    />
                ) : (
                    <ResultsBreakdown
                        result={result}
                        experiment={experiment}
                        metricUuid={metric.uuid || ''}
                        isPrimary={!isSecondary}
                    >
                        {({
                            query,
                            breakdownResultsLoading,
                            breakdownResults,
                            exposureDifference,
                            breakdownLastRefresh,
                        }) => {
                            return (
                                <>
                                    {breakdownResultsLoading && <ResultsBreakdownSkeleton />}
                                    {query && breakdownResults && (
                                        <>
                                            <ResultsInsightInfoBanner exposureDifference={exposureDifference} />
                                            <ResultsQuery
                                                query={query}
                                                breakdownResults={breakdownResults}
                                                breakdownLastRefresh={breakdownLastRefresh}
                                            />
                                        </>
                                    )}
                                </>
                            )
                        }}
                    </ResultsBreakdown>
                ))}
        </div>
    )
}
