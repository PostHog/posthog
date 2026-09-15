import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonTable, LemonTableColumns, LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { ExperimentFunnelChart } from 'scenes/experiments/charts/funnel/ExperimentFunnelChart'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { experimentRecordingsUrl } from 'scenes/experiments/ExperimentView/experimentRecordingsDeepLink'
import { VariantTag } from 'scenes/experiments/ExperimentView/VariantTag'
import { viewRecordingsLinkabilityLogic } from 'scenes/experiments/viewRecordingsLinkabilityLogic'

import {
    CachedNewExperimentQueryResponse,
    ExperimentMetric,
    ExperimentQuery,
    NodeKind,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import {
    ExperimentVariantResult,
    formatChanceToWinForGoal,
    formatIntervalPercent,
    formatMetricValue,
    formatPValue,
    getIntervalLabel,
    isBayesianResult,
    isFrequentistResult,
} from '../shared/utils'
import { getResultRowRecordingLinks } from './resultRowRecordingLinks'

function SqlCollapsible({
    hogql,
    clickhouseSql,
    showClickhouseSql,
    embedded,
}: {
    hogql?: string
    clickhouseSql?: string
    showClickhouseSql: boolean
    embedded?: boolean
}): JSX.Element {
    const [activeTab, setActiveTab] = useState<'hogql' | 'clickhouse'>('hogql')

    return (
        <LemonCollapse
            embedded={embedded}
            panels={[
                {
                    key: 'sql',
                    header: 'SQL',
                    content: showClickhouseSql ? (
                        <LemonTabs
                            activeKey={activeTab}
                            onChange={setActiveTab}
                            tabs={[
                                {
                                    key: 'hogql',
                                    label: 'HogQL',
                                    content: hogql ? (
                                        <CodeSnippet language={Language.SQL} thing="query" className="text-sm">
                                            {hogql}
                                        </CodeSnippet>
                                    ) : (
                                        <div className="text-muted">No HogQL available</div>
                                    ),
                                },
                                {
                                    key: 'clickhouse',
                                    label: 'ClickHouse',
                                    content: clickhouseSql ? (
                                        <CodeSnippet language={Language.SQL} thing="query" className="text-sm">
                                            {clickhouseSql}
                                        </CodeSnippet>
                                    ) : (
                                        <div className="text-muted">No SQL available</div>
                                    ),
                                },
                            ]}
                        />
                    ) : hogql ? (
                        <CodeSnippet language={Language.SQL} thing="query" className="text-sm">
                            {hogql}
                        </CodeSnippet>
                    ) : (
                        <div className="text-muted">No SQL available</div>
                    ),
                },
            ]}
        />
    )
}

export function ResultDetails({
    experiment,
    result,
    metric,
    embedded = false,
}: {
    experiment: Experiment
    result: CachedNewExperimentQueryResponse
    metric: ExperimentMetric
    /** Renders the table, funnel, and SQL as divider-separated sections of a parent panel instead of standalone cards. */
    embedded?: boolean
}): JSX.Element {
    const { featureFlags } = useValues(experimentLogic)
    const { unlinkableEventNames, linkabilityLoaded } = useValues(viewRecordingsLinkabilityLogic({ experiment }))

    const baselineKey = result.baseline?.key
    // Every row links to the same metric, so the labels and the reasons are decided once. An empty
    // set while the check is in flight keeps today's fail-open behavior.
    const recordingLinks = getResultRowRecordingLinks(
        metric,
        linkabilityLoaded ? unlinkableEventNames : new Set<string>()
    )

    const columns: LemonTableColumns<ExperimentVariantResult & { key: string }> = [
        {
            key: 'variant',
            title: 'Variant',
            render: (_, item) => <VariantTag variantKey={item.key} />,
        },
        {
            key: 'total-users',
            title: 'Exposures',
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
        {
            key: 'recordings',
            title: '',
            render: (_, item) => {
                const variantKey = item.key
                return (
                    <div className="flex flex-wrap gap-1">
                        {recordingLinks.map((link) => (
                            <LemonButton
                                key={link.dataAttr}
                                size="xsmall"
                                type="secondary"
                                sideIcon={<IconRewindPlay />}
                                tooltip={link.tooltip}
                                disabledReason={link.disabledReason ?? undefined}
                                to={experimentRecordingsUrl(experiment.id, {
                                    variantKey,
                                    metricUuid: metric.uuid ?? null,
                                    metricFilterMode: link.metricFilterMode,
                                })}
                                data-attr={link.dataAttr}
                                onClick={() => {
                                    // Pinned: a dashboard counts this event. The two properties
                                    // are new, so the count stays comparable across the change.
                                    posthog.capture('viewed recordings from experiment', {
                                        variant: variantKey,
                                        metric_filter: link.metricFilterMode,
                                        metric_kind: metric.metric_type,
                                    })
                                }}
                            >
                                {link.label}
                            </LemonButton>
                        ))}
                    </div>
                )
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
            <SqlCollapsible
                hogql={result.hogql}
                clickhouseSql={result.clickhouse_sql}
                showClickhouseSql={!!featureFlags[FEATURE_FLAGS.EXPERIMENTS_SHOW_SQL]}
                embedded={embedded}
            />
        </div>
    )
}
