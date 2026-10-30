import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSwitch, LemonTag, LemonTagType, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type { TopicClusterApi, UncoveredGroupApi } from '../generated/api.schemas'
import { usageLogic } from '../usageLogic'
import { MetricUsageRow, uncoveredRuns } from '../usageRows'

// The judge step writes the adjusted runs, which the metric table and the topics both read.
const AGENT_COUNTS_MISSING = 'Agent query counts are missing, because the agent query check failed in the last scan.'

function SectionFailed({ reason }: { reason: string }): JSX.Element {
    return (
        <LemonBanner type="warning">
            <div>This section failed in the last scan. Run a new scan to try again.</div>
            <div className="text-xs">{reason}</div>
        </LemonBanner>
    )
}

const OUTCOME_LABELS: Record<string, { label: string; type: LemonTagType }> = {
    covered: { label: 'Covered', type: 'success' },
    slice: { label: 'Covered with a filter', type: 'highlight' },
    uncovered: { label: 'Not covered', type: 'warning' },
}

export function UsageTab(): JSX.Element {
    const {
        latest,
        latestLoadFailed,
        scanRunning,
        newestScan,
        includeScouts,
        metricRows,
        topics,
        uncovered,
        failureReasons,
        recomputedLoading,
    } = useValues(usageLogic)
    const { setIncludeScouts, recompute } = useActions(usageLogic)

    const recomputeButton = (
        <LemonButton
            type="secondary"
            size="small"
            onClick={recompute}
            loading={recomputedLoading}
            disabledReason={scanRunning ? 'A scan is already running' : undefined}
            data-attr="data-catalog-usage-recompute"
        >
            Run a new scan
        </LemonButton>
    )

    if (latestLoadFailed) {
        return (
            <LemonBanner type="error">
                Couldn't load the usage scan. Refresh the page, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (latest === null) {
        return <Spinner />
    }
    if (latest === 'none') {
        return (
            <div className="flex flex-col items-start gap-2">
                <p className="m-0">
                    {scanRunning
                        ? 'A usage scan is running. Results appear here when it finishes.'
                        : 'No usage scan has finished yet. A scan runs every week, or you can start one now.'}
                </p>
                {recomputeButton}
            </div>
        )
    }

    const metricColumns: LemonTableColumns<MetricUsageRow> = [
        {
            title: 'Metric',
            key: 'name',
            render: (_, row) => <span className="inline-block min-w-32">{row.name}</span>,
        },
        {
            title: 'Direct runs',
            key: 'directRuns',
            tooltip: 'Runs of the metric by agents, split by agent. Runs from the web app and the API do not count.',
            render: (_, row) => (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="font-semibold">{row.directRuns}</span>
                    {row.surfaces.map(([surface, runs]) => (
                        <LemonTag key={surface} size="small">
                            {surface} {runs}
                        </LemonTag>
                    ))}
                </div>
            ),
            sorter: (a, b) => a.directRuns - b.directRuns,
        },
        { title: 'People', dataIndex: 'people', key: 'people', sorter: (a, b) => a.people - b.people },
        {
            title: 'Adapted',
            dataIndex: 'adapted',
            key: 'adapted',
            tooltip: 'Agent queries that read the metric first, then changed it.',
            sorter: (a, b) => a.adapted - b.adapted,
        },
        {
            title: 'Missed',
            dataIndex: 'missed',
            key: 'missed',
            tooltip: 'Agent queries that looked at the catalog but computed the metric again in SQL.',
            sorter: (a, b) => a.missed - b.missed,
        },
        {
            title: 'Silent',
            dataIndex: 'silent',
            key: 'silent',
            tooltip: 'Agent queries that computed the metric in SQL without looking at the catalog.',
            sorter: (a, b) => a.silent - b.silent,
        },
    ]

    const topicColumns: LemonTableColumns<TopicClusterApi> = [
        {
            title: 'Topic',
            key: 'title',
            render: (_, topic) => (
                <div className="flex min-w-48 flex-col py-1">
                    <span className="font-semibold">{topic.title}</span>
                    <span className="text-secondary line-clamp-2 text-xs">{topic.sample_intents.join(' / ')}</span>
                </div>
            ),
        },
        { title: 'Sessions', dataIndex: 'session_count', key: 'session_count' },
        { title: 'Ran a metric', key: 'canonical', render: (_, topic) => topic.coverage.canonical },
        { title: 'Adapted', key: 'adapted', render: (_, topic) => topic.coverage.adapted },
        { title: 'Re-derived', key: 'silent', render: (_, topic) => topic.coverage.silent },
        { title: 'Other SQL', key: 'raw_sql_only', render: (_, topic) => topic.coverage.raw_sql_only },
        {
            title: 'Query tool',
            key: 'no_sql',
            tooltip: 'Sessions that queried data with a query tool, without SQL.',
            render: (_, topic) => topic.coverage.no_sql,
        },
    ]

    const uncoveredColumns: LemonTableColumns<UncoveredGroupApi> = [
        {
            title: 'Measure',
            key: 'measure',
            render: (_, group) => <span className="line-clamp-2 font-mono text-xs">{group.measure}</span>,
        },
        {
            title: 'Catalog',
            key: 'outcome',
            render: (_, group) => {
                const outcome = OUTCOME_LABELS[group.outcome] ?? { label: group.outcome, type: 'default' as const }
                return <LemonTag type={outcome.type}>{outcome.label}</LemonTag>
            },
        },
        { title: 'People', dataIndex: 'distinct_people', key: 'distinct_people' },
        { title: 'Days', dataIndex: 'active_days', key: 'active_days' },
        { title: 'Runs', key: 'runs', render: (_, group) => uncoveredRuns(group, includeScouts) },
        { title: 'Proposed name', key: 'draft_name', render: (_, group) => group.draft_name ?? '' },
    ]

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-secondary">
                    Usage from <TZLabel time={latest.window_start} /> to <TZLabel time={latest.window_end} />
                </span>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonSwitch
                        checked={includeScouts}
                        onChange={setIncludeScouts}
                        label="Include scouts"
                        bordered
                        size="small"
                        data-attr="data-catalog-usage-include-scouts"
                    />
                    {recomputeButton}
                </div>
            </div>
            {scanRunning && (
                <LemonBanner type="info">
                    A new scan is running. These results are from the last finished scan.
                </LemonBanner>
            )}
            {newestScan?.status === 'error' && (
                <LemonBanner type="warning">
                    <div>The last scan failed, so these results are from an earlier scan.</div>
                    {newestScan.error_message && <div className="text-xs">{newestScan.error_message}</div>}
                </LemonBanner>
            )}
            <section className="flex flex-col gap-2">
                <h3 className="m-0">Agent metric runs</h3>
                {failureReasons.metric_runs && <SectionFailed reason={failureReasons.metric_runs} />}
                {failureReasons.adjusted_runs && <LemonBanner type="warning">{AGENT_COUNTS_MISSING}</LemonBanner>}
                {!failureReasons.metric_runs && (
                    <LemonTable
                        columns={metricColumns}
                        dataSource={metricRows}
                        rowKey="metricId"
                        size="small"
                        emptyState="No agent ran a catalog metric in this window."
                        data-attr="data-catalog-usage-metric-runs"
                    />
                )}
            </section>
            <section className="flex flex-col gap-2">
                <h3 className="m-0">Agent topics</h3>
                {failureReasons.topics ? (
                    <SectionFailed reason={failureReasons.topics} />
                ) : (
                    failureReasons.adjusted_runs && <LemonBanner type="warning">{AGENT_COUNTS_MISSING}</LemonBanner>
                )}
                {!failureReasons.topics && (
                    <LemonTable
                        columns={topicColumns}
                        dataSource={topics}
                        rowKey="title"
                        size="small"
                        emptyState="No agent session queried data in this window."
                        data-attr="data-catalog-usage-topics"
                    />
                )}
            </section>
            <section className="flex flex-col gap-2">
                <h3 className="m-0">Recurring measures</h3>
                {failureReasons.uncovered && <SectionFailed reason={failureReasons.uncovered} />}
                {!failureReasons.uncovered && (
                    <LemonTable
                        columns={uncoveredColumns}
                        dataSource={uncovered}
                        rowKey="fingerprint_digest"
                        size="small"
                        emptyState="No measure ran often enough in this window."
                        expandable={{
                            expandedRowRender: (group) => (
                                <div className="flex flex-col gap-2 p-2">
                                    {group.draft_description && <p className="m-0">{group.draft_description}</p>}
                                    <CodeSnippet language={Language.SQL} wrap>
                                        {group.draft_definition || group.sample_sql}
                                    </CodeSnippet>
                                </div>
                            ),
                        }}
                        data-attr="data-catalog-usage-uncovered"
                    />
                )}
            </section>
        </div>
    )
}
