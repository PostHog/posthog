import { IconRewindPlay } from '@posthog/icons'
import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { LemonButton } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { humanFriendlyNumber } from 'lib/utils'
import posthog from 'posthog-js'
import { ResultsBreakdown } from 'scenes/experiments/components/ResultsBreakdown/ResultsBreakdown'
import { ResultsBreakdownSkeleton } from 'scenes/experiments/components/ResultsBreakdown/ResultsBreakdownSkeleton'
import { ResultsQuery } from 'scenes/experiments/components/ResultsBreakdown/ResultsQuery'
import { getViewRecordingFilters } from 'scenes/experiments/utils'
import { urls } from 'scenes/urls'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, RecordingUniversalFilters, ReplayTabs } from '~/types'
import { Experiment } from '~/types'

import { formatPValue } from '../shared/utils'

export function ResultDetails({
    experiment,
    result,
    metric,
}: {
    experiment: Experiment
    result: CachedExperimentQueryResponse
    metric: ExperimentMetric
}): JSX.Element {
    const columns: LemonTableColumns<any> = [
        {
            key: 'variant',
            title: 'Variant',
            render: (_, item) => <div className="font-semibold">{item.key}</div>,
        },
        {
            key: 'value',
            title: metric.metric_type === 'mean' ? 'Mean' : 'Conversion rate',
            render: (_, item) => {
                const value = item.sum / item.number_of_samples
                return metric.metric_type === 'mean' ? value.toFixed(2) : `${(value * 100).toFixed(2)}%`
            },
        },
        {
            key: 'samples',
            title: 'Samples',
            render: (_, item) => humanFriendlyNumber(item.number_of_samples),
        },
        {
            key: 'p_value',
            title: 'p-value',
            render: (_, item) => {
                if (item.key === 'control') {
                    return '—'
                }
                if ('p_value' in item) {
                    return <div className="font-semibold">{formatPValue(item.p_value)}</div>
                }
                return '—'
            },
        },
        {
            key: 'significant',
            title: 'Significant',
            render: (_, item) => {
                if (item.key === 'control') {
                    return '—'
                }
                return item.significant ? <div className="text-success font-semibold">Yes</div> : 'No'
            },
        },
        {
            key: 'interval',
            title: 'Confidence interval (95%)',
            render: (_, item) => {
                if (item.key === 'control') {
                    return '—'
                }
                const interval = 'confidence_interval' in item ? item.confidence_interval : null
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

    const dataSource = [{ ...result.baseline, key: 'control' }, ...(result.variant_results || [])]

    return (
        <div className="space-y-2">
            <LemonTable columns={columns} dataSource={dataSource} loading={false} />
            {metric.metric_type === 'funnel' && (
                <ResultsBreakdown result={result} experiment={experiment}>
                    {({ query, breakdownResultsLoading, breakdownResults }) => {
                        return (
                            <>
                                {breakdownResultsLoading && <ResultsBreakdownSkeleton />}
                                {query && breakdownResults && (
                                    <ResultsQuery query={query} breakdownResults={breakdownResults} />
                                )}
                            </>
                        )
                    }}
                </ResultsBreakdown>
            )}
        </div>
    )
}
