import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'
import { ResultsBreakdown } from 'scenes/experiments/components/ResultsBreakdown/ResultsBreakdown'
import { ResultsBreakdownSkeleton } from 'scenes/experiments/components/ResultsBreakdown/ResultsBreakdownSkeleton'
import { ResultsInsightInfoBanner } from 'scenes/experiments/components/ResultsBreakdown/ResultsInsightInfoBanner'
import { ResultsQuery } from 'scenes/experiments/components/ResultsBreakdown/ResultsQuery'
import { getViewRecordingFilters } from 'scenes/experiments/utils'
import { urls } from 'scenes/urls'

import {
    CachedExperimentQueryResponse,
    ExperimentMetric,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { Experiment, FilterLogicalOperator, RecordingUniversalFilters, ReplayTabs } from '~/types'

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

export function ResultDetails({
    experiment,
    result,
    metric,
    isSecondary,
}: {
    experiment: Experiment
    result: CachedExperimentQueryResponse
    metric: ExperimentMetric
    isSecondary: boolean
}): JSX.Element {
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
            {isExperimentFunnelMetric(metric) && (
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
            )}
        </div>
    )
}
