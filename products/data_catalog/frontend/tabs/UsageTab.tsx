import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils/strings'

import { newMetricUrl } from '../common'
import type { TopicClusterApi } from '../generated/api.schemas'
import { ProposedRow, proposedRowPrefill } from '../proposedRows'
import { usageLogic } from '../usageLogic'
import { SourceRow } from '../usageRows'
import { ProposedMetricSources } from './ProposedMetricSources'
import { ProposedRowDerivedFrom } from './ProposedRowDerivedFrom'
import { TopicCoverageBar } from './TopicCoverageBar'

// LemonTable keeps its page in the URL under its id, so tables on one page need their own ids to page apart.
const TOPICS_TABLE_ID = 'usage-topics'
const SOURCES_TABLE_ID = 'usage-sources'
const COMPLEXITY_LABELS: Record<number, string> = { 0: 'Unknown', 1: 'Low', 2: 'Medium', 3: 'High' }
const PROPOSED_TABLE_ID = 'usage-proposed'
const HALF_TABLE_PAGE_SIZE = 6
const PROPOSED_PAGE_SIZE = 10
// The two tables on the top row sit side by side, so every row holds one line of one height.
const SINGLE_LINE_ROW = 'flex h-7 items-center'

// The judge step writes the adjusted runs, which tell the topics which sessions adapted a metric they read.
const AGENT_COUNTS_MISSING =
    'Coverage can miss metrics that agents adapted, because the agent query check failed in the last scan.'

function SectionFailed({ reason }: { reason: string }): JSX.Element {
    return (
        <LemonBanner type="warning">
            <div>This section failed in the last scan. Run a new scan to try again.</div>
            <div className="text-xs">{reason}</div>
        </LemonBanner>
    )
}

export function UsageTab(): JSX.Element {
    const {
        latest,
        latestLoadFailed,
        scanRunning,
        newestScan,
        sourceRows,
        proposedRows,
        metricsById,
        topics,
        topicSessionsSummary,
        failureReasons,
        recomputedLoading,
    } = useValues(usageLogic)
    const { recompute } = useActions(usageLogic)

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

    const sourceColumns: LemonTableColumns<SourceRow> = [
        {
            title: 'Source',
            key: 'name',
            render: (_, row) => (
                <div className={`${SINGLE_LINE_ROW} max-w-96 min-w-32 gap-2`}>
                    <span className="truncate" title={row.name}>
                        {row.name}
                    </span>
                    <LemonTag size="small">{row.kind === 'metric' ? 'Metric' : 'Table'}</LemonTag>
                </div>
            ),
        },
        {
            title: 'Usage',
            key: 'usage',
            tooltip:
                'Metrics count the runs by agents. Tables count the agent sessions that found a connected source or a view through its description and then queried it. PostHog tables such as events stay out. Both cover the whole window. Hover a metric to split its runs by agent.',
            render: (_, row) => (
                <Tooltip title={row.surfaces.map(([surface, runs]) => `${surface}: ${runs}`).join(', ') || undefined}>
                    <span className="font-semibold whitespace-nowrap">
                        {pluralize(row.uses, row.kind === 'metric' ? 'run' : 'session')} /{' '}
                        {pluralize(row.people, 'person', 'people')}
                    </span>
                </Tooltip>
            ),
            sorter: (a, b) => a.people - b.people || a.uses - b.uses,
        },
    ]

    // One scale for every topic, so a bar's length shows how many sessions asked.
    const maxAsked = Math.max(1, ...topics.map(({ coverage }) => coverage.metric + coverage.table + coverage.nothing))

    const topicColumns: LemonTableColumns<TopicClusterApi> = [
        {
            title: 'Topic',
            key: 'title',
            render: (_, topic) => (
                <div className={`${SINGLE_LINE_ROW} max-w-64 min-w-40`}>
                    <span className="truncate font-semibold" title={topic.title}>
                        {topic.title}
                    </span>
                </div>
            ),
        },
        { title: 'People', dataIndex: 'people', key: 'people' },
        { title: 'Sessions', dataIndex: 'session_count', key: 'session_count' },
        {
            title: 'Catalog coverage',
            key: 'coverage',
            width: '40%',
            tooltip:
                'The number is how many sessions looked for a metric in the catalog. Bars use one scale for every topic. Coral: found a metric that fits. Purple: no metric, but found a table. Blue: found nothing. Each session counts once, and a metric comes first.',
            render: (_, topic) => <TopicCoverageBar coverage={topic.coverage} maxAsked={maxAsked} />,
        },
    ]

    const proposedColumns: LemonTableColumns<ProposedRow> = [
        {
            title: 'Proposed metric',
            key: 'name',
            render: (_, row) => (
                <div className="flex max-w-80 min-w-40 flex-col py-1">
                    <Link
                        to={newMetricUrl(proposedRowPrefill(row))}
                        className={row.name ? 'font-semibold' : 'line-clamp-2 font-mono text-xs'}
                        data-attr="data-catalog-usage-proposed-metric-link"
                    >
                        {row.name ?? row.measure}
                    </Link>
                    {row.description && (
                        <Tooltip title={row.description}>
                            <span className="text-secondary truncate text-xs">{row.description}</span>
                        </Tooltip>
                    )}
                    {row.outcome === 'slice' && (
                        <ProposedRowDerivedFrom metric={metricsById[row.matchedMetricId ?? '']} />
                    )}
                </div>
            ),
        },
        {
            title: 'Where it is used',
            key: 'sources',
            tooltip: 'Where people wrote the query and where they saw it.',
            render: (_, row) => (
                <div className="min-w-80">
                    <ProposedMetricSources metric={row} />
                </div>
            ),
        },
        {
            title: 'Complexity',
            key: 'complexity',
            tooltip:
                'How hard the query is to write by hand. Joins, subqueries, window functions, conditional aggregates and calculations raise it. Complex queries come first, because they most need one shared definition.',
            render: (_, row) => COMPLEXITY_LABELS[row.complexity] ?? COMPLEXITY_LABELS[0],
        },
        {
            title: 'People',
            dataIndex: 'people',
            key: 'people',
            tooltip: 'People who wrote the query or created a chart of it, directly or through an agent.',
        },
        {
            title: 'Built',
            dataIndex: 'built',
            key: 'built',
            tooltip:
                'Each time a person or an agent wrote the query, plus one for each saved chart and each query in a notebook or canvas.',
        },
        {
            title: 'Viewed',
            dataIndex: 'viewed',
            key: 'viewed',
            tooltip: 'Runs that a person saw, in the web app or an agent session. Whoever builds a query also sees it.',
        },
    ]

    return (
        <div className="flex flex-col gap-6">
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
            <div className="@container">
                <div className="grid grid-cols-1 items-start gap-6 @4xl:grid-cols-2">
                    <section className="flex min-w-0 flex-col gap-2">
                        <h3 className="m-0 flex min-h-6 items-center gap-1">
                            Top agent topics
                            {!failureReasons.topics && topicSessionsSummary && (
                                <Tooltip title={topicSessionsSummary}>
                                    <IconInfo className="text-secondary text-base" />
                                </Tooltip>
                            )}
                        </h3>
                        {failureReasons.topics ? (
                            <SectionFailed reason={failureReasons.topics} />
                        ) : (
                            failureReasons.adjusted_runs && (
                                <LemonBanner type="warning">{AGENT_COUNTS_MISSING}</LemonBanner>
                            )
                        )}
                        {!failureReasons.topics && (
                            <LemonTable
                                id={TOPICS_TABLE_ID}
                                columns={topicColumns}
                                dataSource={topics}
                                rowKey="title"
                                size="small"
                                pagination={{ pageSize: HALF_TABLE_PAGE_SIZE, hideOnSinglePage: true }}
                                emptyState="No agent session analyzed data in this window."
                                data-attr="data-catalog-usage-topics"
                            />
                        )}
                    </section>
                    <section className="flex min-w-0 flex-col gap-2">
                        <h3 className="m-0 flex min-h-6 items-center">Top used sources</h3>
                        {failureReasons.metric_runs && <SectionFailed reason={failureReasons.metric_runs} />}
                        {failureReasons.table_sources && (
                            <LemonBanner type="warning">
                                Table counts are missing, because the table check failed in the last scan.
                            </LemonBanner>
                        )}
                        {!failureReasons.metric_runs && (
                            <LemonTable
                                id={SOURCES_TABLE_ID}
                                columns={sourceColumns}
                                dataSource={sourceRows}
                                rowKey="key"
                                size="small"
                                pagination={{ pageSize: HALF_TABLE_PAGE_SIZE, hideOnSinglePage: true }}
                                emptyState="No agent ran a catalog metric or found a table by its description in this window."
                                data-attr="data-catalog-usage-sources"
                            />
                        )}
                    </section>
                </div>
            </div>
            <section className="flex flex-col gap-2">
                <h3 className="m-0">Proposed metrics</h3>
                {failureReasons.uncovered && <SectionFailed reason={failureReasons.uncovered} />}
                {!failureReasons.uncovered && (
                    <LemonTable
                        id={PROPOSED_TABLE_ID}
                        columns={proposedColumns}
                        dataSource={proposedRows}
                        rowKey="key"
                        size="small"
                        pagination={{ pageSize: PROPOSED_PAGE_SIZE, hideOnSinglePage: true }}
                        emptyState="No measure needs a metric yet. One appears here once several people compute the same measure."
                        expandable={{
                            expandedRowRender: (row) => (
                                <div className="flex flex-col gap-2 p-2">
                                    {row.measures > 1 && (
                                        <p className="m-0">This proposal merges {row.measures} recurring measures.</p>
                                    )}
                                    <CodeSnippet language={Language.SQL} wrap>
                                        {row.sql}
                                    </CodeSnippet>
                                </div>
                            ),
                        }}
                        data-attr="data-catalog-usage-proposed"
                    />
                )}
            </section>
        </div>
    )
}
