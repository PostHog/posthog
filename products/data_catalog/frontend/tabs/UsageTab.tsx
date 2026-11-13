import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { newMetricUrl } from '../common'
import type { TopicClusterApi, UsageSnapshotApi } from '../generated/api.schemas'
import { ProposedRow, complexityLabel, proposedRowPrefill } from '../proposedRows'
import { usageLogic } from '../usageLogic'
import { SourceRow, agentSurfaceLabel } from '../usageRows'
import { ProposedMetricSources } from './ProposedMetricSources'
import { ProposedRowDerivedFrom } from './ProposedRowDerivedFrom'
import { TopicCoverageBar } from './TopicCoverageBar'

// LemonTable keeps its page in the URL under its id, so tables on one page need their own ids to page apart.
const TOPICS_TABLE_ID = 'usage-topics'
const SOURCES_TABLE_ID = 'usage-sources'
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
            <div>This section failed in the last scan. The next weekly scan tries again.</div>
            <div className="text-xs">{reason}</div>
        </LemonBanner>
    )
}

const SOURCE_COLUMNS: LemonTableColumns<SourceRow> = [
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
            'Metrics count the runs by agents. Tables count the agent sessions that found a connected source or a view through its description and then queried it. PostHog tables such as events stay out. Both cover the whole scan window. Hover a metric to split its runs by agent.',
        render: (_, row) => (
            <Tooltip
                title={
                    row.surfaces
                        .map(([surface, runs]) => `${agentSurfaceLabel(surface)}: ${humanFriendlyNumber(runs)}`)
                        .join(', ') || undefined
                }
            >
                <span className="font-semibold whitespace-nowrap">
                    {pluralize(row.uses, row.kind === 'metric' ? 'run' : 'session')} /{' '}
                    {pluralize(row.people, 'person', 'people')}
                </span>
            </Tooltip>
        ),
        sorter: (a, b) => a.people - b.people || a.uses - b.uses,
    },
]

const TOPIC_COLUMNS: LemonTableColumns<TopicClusterApi> = [
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
            'The number is how many sessions looked for a metric in the catalog. Each bar splits those sessions by what they found: a metric that fits, a table but no metric, or nothing. Hover a part of the bar to see its sessions. Each session counts once, and a metric comes first.',
        render: (_, topic) => (
            <div className={SINGLE_LINE_ROW}>
                <TopicCoverageBar coverage={topic.coverage} />
            </div>
        ),
    },
]

function ProposedMetricName({ row }: { row: ProposedRow }): JSX.Element {
    const { metricsById } = useValues(usageLogic)
    return (
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
            {row.outcome === 'slice' && <ProposedRowDerivedFrom metric={metricsById[row.matchedMetricId ?? '']} />}
        </div>
    )
}

const PROPOSED_COLUMNS: LemonTableColumns<ProposedRow> = [
    {
        title: 'Proposed metric',
        key: 'name',
        render: (_, row) => <ProposedMetricName row={row} />,
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
        render: (_, row) => complexityLabel(row.complexity),
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

function RecomputeButton(): JSX.Element {
    const { recomputeDisabledReason, recomputedLoading } = useValues(usageLogic)
    const { recompute } = useActions(usageLogic)
    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={recompute}
            loading={recomputedLoading}
            disabledReason={recomputeDisabledReason}
            data-attr="data-catalog-usage-recompute"
        >
            Run a new scan
        </LemonButton>
    )
}

function UsageEmptyState(): JSX.Element {
    const { newestScan, scanRunning } = useValues(usageLogic)
    return (
        <div className="flex flex-col items-start gap-2">
            {newestScan?.status === 'error' && (
                <LemonBanner type="warning" className="self-stretch">
                    <div>The last scan failed.</div>
                    {newestScan.error_message && <div className="text-xs">{newestScan.error_message}</div>}
                </LemonBanner>
            )}
            <p className="m-0">
                {scanRunning
                    ? 'A usage scan is running. Results appear here when it finishes.'
                    : 'No usage scan has finished yet. A scan runs every week, or you can start one now.'}
            </p>
            <RecomputeButton />
        </div>
    )
}

function ScanWindow({ scan }: { scan: UsageSnapshotApi }): JSX.Element {
    return (
        <p className="text-secondary m-0 text-xs">
            Usage from <TZLabel time={scan.window_start} /> to <TZLabel time={scan.window_end} />
            {scan.computed_at && (
                <>
                    , scanned <TZLabel time={scan.computed_at} />
                </>
            )}
            .
        </p>
    )
}

function TopicsSection(): JSX.Element {
    const { topics, topicSessionsSummary, failureReasons } = useValues(usageLogic)
    return (
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
                <>
                    {failureReasons.adjusted_runs && <LemonBanner type="warning">{AGENT_COUNTS_MISSING}</LemonBanner>}
                    <LemonTable
                        id={TOPICS_TABLE_ID}
                        columns={TOPIC_COLUMNS}
                        dataSource={topics}
                        rowKey="title"
                        size="small"
                        pagination={{ pageSize: HALF_TABLE_PAGE_SIZE, hideOnSinglePage: true }}
                        emptyState="No agent session analyzed data in this window."
                        data-attr="data-catalog-usage-topics"
                    />
                </>
            )}
        </section>
    )
}

function SourcesSection(): JSX.Element {
    const { sourceRows, failureReasons, metricsLoadState } = useValues(usageLogic)
    return (
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
                    columns={SOURCE_COLUMNS}
                    dataSource={sourceRows}
                    loading={metricsLoadState === 'unknown'}
                    rowKey="key"
                    size="small"
                    pagination={{ pageSize: HALF_TABLE_PAGE_SIZE, hideOnSinglePage: true }}
                    emptyState="No agent ran a catalog metric or found a table by its description in this window."
                    data-attr="data-catalog-usage-sources"
                />
            )}
        </section>
    )
}

function ProposedSection(): JSX.Element {
    const { proposedRows, failureReasons } = useValues(usageLogic)
    return (
        <section className="flex flex-col gap-2">
            <h3 className="m-0">Proposed metrics</h3>
            {failureReasons.uncovered ? (
                <SectionFailed reason={failureReasons.uncovered} />
            ) : (
                <LemonTable
                    id={PROPOSED_TABLE_ID}
                    columns={PROPOSED_COLUMNS}
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
    )
}

export function UsageTab(): JSX.Element {
    const { latest, latestLoadFailed, usageUnavailable, scanRunning, newestScan } = useValues(usageLogic)

    if (usageUnavailable) {
        return <LemonBanner type="info">Usage scans aren't available for this project.</LemonBanner>
    }
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
        return <UsageEmptyState />
    }

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
            <div className="flex flex-col gap-2">
                <ScanWindow scan={latest} />
                <div className="@container">
                    <div className="grid grid-cols-1 items-start gap-6 @4xl:grid-cols-2">
                        <TopicsSection />
                        <SourcesSection />
                    </div>
                </div>
            </div>
            <ProposedSection />
        </div>
    )
}
