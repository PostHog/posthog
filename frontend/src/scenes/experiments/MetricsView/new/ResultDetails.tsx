import { useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { ExperimentFunnelChart } from 'scenes/experiments/charts/funnel/ExperimentFunnelChart'
import { VariantTag } from 'scenes/experiments/ExperimentView/VariantTag'
import { teamLogic } from 'scenes/teamLogic'

import {
    CachedNewExperimentQueryResponse,
    ExperimentMetric,
    ExperimentQuery,
    NodeKind,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentQuantileMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import {
    ExperimentVariantResult,
    formatChanceToWinForGoal,
    formatIntervalPercent,
    formatMetricValue,
    formatPValue,
    formatQuantileLevel,
    getIntervalLabel,
    isBayesianResult,
    isFrequentistResult,
} from '../shared/utils'

export function ResultDetails({
    experiment,
    result,
    metric,
    embedded = false,
}: {
    experiment: Experiment
    result: CachedNewExperimentQueryResponse
    metric: ExperimentMetric
    /** Renders the table and funnel as divider-separated sections of a parent panel instead of standalone cards. */
    embedded?: boolean
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)

    const baselineKey = result.baseline?.key

    const columns: LemonTableColumns<ExperimentVariantResult & { key: string }> = [
        {
            key: 'variant',
            title: 'Variant',
            render: (_, item) => <VariantTag variantKey={item.key} />,
        },
        {
            key: 'total-users',
            title: 'Exposures',
            tooltip:
                "Exposures counted by this metric's query, so the count can differ from the Exposures panel. With 'Require completed conversion or retention window' enabled, users whose window hasn't elapsed are excluded.",
            render: (_, item) => humanFriendlyNumber(item.number_of_samples),
        },
        ...(isExperimentQuantileMetric(metric)
            ? [
                  {
                      key: 'events',
                      title: 'Events',
                      tooltip: 'Events with a value for the property. The percentile is taken over these events.',
                      render: (_: unknown, item: ExperimentVariantResult & { key: string }) =>
                          humanFriendlyNumber(item.denominator_sum ?? 0),
                  },
              ]
            : []),
        {
            key: 'value',
            title: isExperimentMeanMetric(metric)
                ? 'Mean'
                : isExperimentRatioMetric(metric)
                  ? 'Ratio'
                  : isExperimentQuantileMetric(metric)
                    ? formatQuantileLevel(metric.quantile)
                    : 'Conversion rate',
            render: (_, item) => formatMetricValue(item, metric, baseCurrency),
        },
        {
            key: 'statistical_measure',
            title:
                result.variant_results?.[0] && isBayesianResult(result.variant_results[0])
                    ? 'Chance to win'
                    : 'p-value',
            render: (_, item: ExperimentVariantResult & { key: string }) => {
                if (item.key === baselineKey) {
                    return '—'
                }

                if (isBayesianResult(item)) {
                    return <div className="font-semibold">{formatChanceToWinForGoal(item, metric.goal)}</div>
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
                if (item.key === baselineKey) {
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
            tooltip:
                "The range that likely contains the true effect. When it doesn't cross 0%, the result is significant.",
            render: (_, item: ExperimentVariantResult & { key: string }) => {
                if (item.key === baselineKey) {
                    return '—'
                }
                return formatIntervalPercent(item)
            },
        },
    ]

    const dataSource = [
        ...(result.baseline ? [result.baseline as ExperimentVariantResult & { key: string }] : []),
        ...(result.variant_results || []),
    ]

    // Construct ExperimentQuery for actors query
    const experimentQuery: ExperimentQuery | undefined = experiment.id
        ? ({
              kind: NodeKind.ExperimentQuery,
              experiment_id: experiment.id,
              metric,
          } as ExperimentQuery)
        : undefined

    return (
        <div className={embedded ? 'divide-y divide-border' : 'space-y-4'}>
            <LemonTable columns={columns} dataSource={dataSource} loading={false} embedded={embedded} />
            {isExperimentFunnelMetric(metric) && (
                <ExperimentFunnelChart
                    result={result}
                    experiment={experiment}
                    metric={metric}
                    experimentQuery={experimentQuery}
                    embedded={embedded}
                />
            )}
        </div>
    )
}
