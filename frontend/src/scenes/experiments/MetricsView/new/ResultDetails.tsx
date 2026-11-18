import clsx from 'clsx'
import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { ExperimentFunnelChart } from 'scenes/experiments/charts/funnel/ExperimentFunnelChart'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { getMetricRecordingModes } from 'scenes/experiments/ExperimentView/experimentRecordingModes'
import { VariantTag } from 'scenes/experiments/ExperimentView/VariantTag'
import { viewRecordingsLinkabilityLogic } from 'scenes/experiments/viewRecordingsLinkabilityLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    CachedNewExperimentQueryResponse,
    ExperimentMetric,
    ExperimentQuery,
    NewExperimentQueryResponse,
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
import { type ExperimentResultsSurface, VariantRecordingsButton } from './VariantRecordingsButton'

export const RESULT_EXPOSURES_HELP =
    "Exposures counted by this metric's query, so the count can differ from the Exposures panel. With 'Require completed conversion or retention window' enabled, users whose window hasn't elapsed are excluded."
export const RESULT_EVENTS_HELP = 'Events with a value for the property. The percentile is taken over these events.'
export const RESULT_INTERVAL_HELP =
    "The range that likely contains the true effect. When it doesn't cross 0%, the result is significant."

export function resultValueLabel(metric: ExperimentMetric): string {
    return isExperimentMeanMetric(metric)
        ? 'Mean'
        : isExperimentRatioMetric(metric)
          ? 'Ratio'
          : isExperimentQuantileMetric(metric)
            ? formatQuantileLevel(metric.quantile)
            : 'Conversion rate'
}

export function statisticalMeasureLabel(result: NewExperimentQueryResponse): string {
    return result.variant_results?.[0] && isBayesianResult(result.variant_results[0]) ? 'Chance to win' : 'p-value'
}

export function resultIntervalLabel(result: NewExperimentQueryResponse): string {
    return result.variant_results?.[0]
        ? `${getIntervalLabel(result.variant_results[0])} (95%)`
        : 'Confidence interval (95%)'
}

export function resultExperimentQuery(experiment: Experiment, metric: ExperimentMetric): ExperimentQuery | undefined {
    return experiment.id
        ? ({
              kind: NodeKind.ExperimentQuery,
              experiment_id: experiment.id,
              metric,
          } as ExperimentQuery)
        : undefined
}

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
    const [isOpen, setIsOpen] = useState(false)
    const [activeTab, setActiveTab] = useState<'hogql' | 'clickhouse'>('hogql')

    const hogqlSnippet = hogql ? (
        <CodeSnippet language={Language.SQL} thing="query" className="text-sm">
            {hogql}
        </CodeSnippet>
    ) : (
        <div className="text-xs text-secondary">No HogQL available</div>
    )

    return (
        <div className={embedded ? 'px-2 py-1' : undefined}>
            <LemonButton
                size="xsmall"
                type="tertiary"
                // One glyph rotated rather than a chevron pair: IconChevronRight is drawn three times
                // taller than IconChevronDown in this set, so the two states would change size.
                icon={
                    <IconChevronDown className={clsx('text-secondary transition-transform', !isOpen && '-rotate-90')} />
                }
                onClick={() => setIsOpen(!isOpen)}
                aria-expanded={isOpen}
                data-attr="experiment-result-sql-toggle"
            >
                <span className="text-secondary font-normal">SQL</span>
            </LemonButton>
            {isOpen && (
                <div className="mt-1">
                    {showClickhouseSql ? (
                        <LemonTabs
                            size="small"
                            activeKey={activeTab}
                            onChange={setActiveTab}
                            tabs={[
                                {
                                    key: 'hogql',
                                    label: 'HogQL',
                                    content: hogqlSnippet,
                                },
                                {
                                    key: 'clickhouse',
                                    label: 'ClickHouse',
                                    content: clickhouseSql ? (
                                        <CodeSnippet language={Language.SQL} thing="query" className="text-sm">
                                            {clickhouseSql}
                                        </CodeSnippet>
                                    ) : (
                                        <div className="text-xs text-secondary">No SQL available</div>
                                    ),
                                },
                            ]}
                        />
                    ) : (
                        hogqlSnippet
                    )}
                </div>
            )}
        </div>
    )
}

export function ResultDetails({
    experiment,
    result,
    metric,
    embedded = false,
    surface = 'inline',
}: {
    experiment: Experiment
    result: CachedNewExperimentQueryResponse
    metric: ExperimentMetric
    /** Renders the table, funnel, and SQL as divider-separated sections of a parent panel instead of standalone cards. */
    embedded?: boolean
    surface?: ExperimentResultsSurface
}): JSX.Element {
    const { featureFlags } = useValues(experimentLogic)
    const { baseCurrency } = useValues(teamLogic)
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const { unlinkableEventNames, linkabilityLoaded } = useValues(viewRecordingsLinkabilityLogic({ experiment }))

    const baselineKey = result.baseline?.key
    // Every row links to the same metric, so the labels and the reasons are decided once. An empty
    // set while the check is in flight keeps today's fail-open behavior.
    const recordingModes = getMetricRecordingModes(metric, linkabilityLoaded ? unlinkableEventNames : new Set<string>())

    const columns: LemonTableColumns<ExperimentVariantResult & { key: string }> = [
        {
            key: 'variant',
            title: 'Variant',
            render: (_, item) => <VariantTag variantKey={item.key} />,
        },
        {
            key: 'total-users',
            title: 'Exposures',
            tooltip: RESULT_EXPOSURES_HELP,
            render: (_, item) => humanFriendlyNumber(item.number_of_samples),
        },
        ...(isExperimentQuantileMetric(metric)
            ? [
                  {
                      key: 'events',
                      title: 'Events',
                      tooltip: RESULT_EVENTS_HELP,
                      render: (_: unknown, item: ExperimentVariantResult & { key: string }) =>
                          humanFriendlyNumber(item.denominator_sum ?? 0),
                  },
              ]
            : []),
        {
            key: 'value',
            title: resultValueLabel(metric),
            render: (_, item) => formatMetricValue(item, metric, baseCurrency),
        },
        {
            key: 'statistical_measure',
            title: statisticalMeasureLabel(result),
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
            title: resultIntervalLabel(result),
            tooltip: RESULT_INTERVAL_HELP,
            render: (_, item: ExperimentVariantResult & { key: string }) => {
                if (item.key === baselineKey) {
                    return '—'
                }
                return formatIntervalPercent(item)
            },
        },
        ...(resultsRedesign
            ? []
            : [
                  {
                      key: 'recordings',
                      title: '',
                      render: (_: unknown, item: ExperimentVariantResult & { key: string }) => (
                          <div className="flex justify-end">
                              <VariantRecordingsButton
                                  experiment={experiment}
                                  metric={metric}
                                  variantKey={item.key}
                                  isBaseline={item.key === baselineKey}
                                  surface={surface}
                                  modes={recordingModes}
                              />
                          </div>
                      ),
                  },
              ]),
    ]

    const dataSource = [
        ...(result.baseline ? [result.baseline as ExperimentVariantResult & { key: string }] : []),
        ...(result.variant_results || []),
    ]

    const experimentQuery = resultExperimentQuery(experiment, metric)

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
            {!resultsRedesign && (
                <SqlCollapsible
                    hogql={result.hogql}
                    clickhouseSql={result.clickhouse_sql}
                    showClickhouseSql={!!featureFlags[FEATURE_FLAGS.EXPERIMENTS_SHOW_SQL]}
                    embedded={embedded}
                />
            )}
        </div>
    )
}
