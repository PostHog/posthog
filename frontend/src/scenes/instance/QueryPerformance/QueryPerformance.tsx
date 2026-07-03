import { useActions, useValues } from 'kea'

import { IconDatabase } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LinkMetabaseQuery } from 'lib/components/MetabaseQueryLink'
import { dayjs } from 'lib/dayjs'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanizeBytes } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PrecomputationTeam, queryPerformanceLogic, SlowestQuery } from './queryPerformanceLogic'

export const scene: SceneExport = {
    component: QueryPerformance,
    logic: queryPerformanceLogic,
}

const TIME_RANGE_OPTIONS = [
    { label: '1h', hours: 1 },
    { label: '6h', hours: 6 },
    { label: '24h', hours: 24 },
    { label: '7d', hours: 168 },
]

// Value is the metric_type, or "funnel:<orderType>" to also filter the funnel order.
const METRIC_TYPE_OPTIONS = [
    { value: '', label: 'All metric types' },
    { value: 'mean', label: 'Mean' },
    { value: 'funnel', label: 'Funnel (any order)' },
    { value: 'funnel:ordered', label: 'Funnel: ordered' },
    { value: 'funnel:unordered', label: 'Funnel: unordered' },
    { value: 'funnel:strict', label: 'Funnel: strict' },
    { value: 'ratio', label: 'Ratio' },
    { value: 'retention', label: 'Retention' },
]

// Group total = the read plus its precompute-build sub-queries (the user paid for all of them),
// mirroring how the Duration column sums total_duration_ms over the group.
const groupBytes = (item: SlowestQuery): number =>
    item.read_bytes + item.sub_queries.reduce((sum, q) => sum + q.read_bytes, 0)

// Off/gated reasons come straight from the runner tag; build-failed/not-ready are derived from the
// precompute-build sub-queries. Empty tag + no sub-queries is the legacy/forward-only case ("not ready").
const SKIP_REASON_LABELS: Record<string, string> = {
    override_direct: 'forced direct (query override)',
    team_disabled: 'precompute off for team',
    min_runtime: 'experiment <12h old',
    data_warehouse: 'data warehouse metric',
}

function reasonForDirect(item: SlowestQuery, table: 'exposures' | 'metric_events'): string {
    const skip = item.experiment_precompute_skip_reason
    if (skip && SKIP_REASON_LABELS[skip]) {
        return SKIP_REASON_LABELS[skip]
    }
    const builds = item.sub_queries.filter((q) => q.experiment_precompute_table === table)
    const failed = builds.find((q) => q.exception)
    if (failed) {
        return `build failed (${failed.exception_code || 'error'})`
    }
    if (builds.length > 0) {
        return 'build incomplete / not ready'
    }
    return 'not ready'
}

const EXCEPTION_CODE_LABELS: Record<number, string> = {
    307: 'exceeded byte limit',
    159: 'timeout',
    241: 'out of memory',
    202: 'cluster busy',
}

const codeLabel = (code: number): string => EXCEPTION_CODE_LABELS[code] ?? `error ${code}`

// One-glance terminal result for the group: the read plus its precompute builds. exception_code 0 = ok.
function outcome(item: SlowestQuery): { label: string; type: LemonTagType } {
    const parentFailed = item.exception_code !== 0
    const buildFailed = item.sub_queries.some((q) => q.exception_code !== 0)
    if (!parentFailed && !buildFailed) {
        return { label: 'OK', type: 'success' }
    }
    if (parentFailed && buildFailed) {
        return { label: `Build + read ${codeLabel(item.exception_code)}`, type: 'danger' }
    }
    if (parentFailed) {
        return { label: `Read ${codeLabel(item.exception_code)}`, type: 'danger' }
    }
    return { label: 'Build failed', type: 'warning' }
}

// Compact day-span of a scan window, exact dates on hover. Renders nothing for pre-tag (empty) rows.
function ScanWindow({ from, to }: { from: string; to: string }): JSX.Element | null {
    if (!from || !to) {
        return null
    }
    const days = Math.max(1, dayjs(to).diff(dayjs(from), 'day'))
    return (
        <Tooltip title={`${from} → ${to}`}>
            <span className="font-mono text-xs">{days}d</span>
        </Tooltip>
    )
}

function QueryStats({
    read_bytes,
    read_rows,
    memory_usage,
    exception_code,
}: Pick<SlowestQuery, 'read_bytes' | 'read_rows' | 'memory_usage' | 'exception_code'>): JSX.Element {
    return (
        <div className="font-mono text-xs text-muted">
            Read {humanizeBytes(read_bytes)} · {read_rows.toLocaleString()} rows
            {memory_usage ? ` · ${humanizeBytes(memory_usage)} peak memory` : ''}
            {exception_code ? ` · exit code ${exception_code}` : ''}
        </div>
    )
}

export function QueryPerformance(): JSX.Element {
    const { user } = useValues(userLogic)
    const {
        precomputationTeams,
        precomputationTeamsLoading,
        search,
        slowestQueries,
        slowestQueriesLoading,
        hoursBack,
        teamIdFilter,
        experimentIdFilter,
        metricTypeFilter,
    } = useValues(queryPerformanceLogic)
    const {
        setSearch,
        setPrecomputation,
        setHoursBack,
        loadSlowestQueries,
        setTeamIdFilter,
        setExperimentIdFilter,
        setMetricTypeFilter,
    } = useActions(queryPerformanceLogic)

    if (!user?.is_staff) {
        return (
            <>
                <SceneTitleSection
                    name="Query performance"
                    description="Internal tooling for monitoring and managing query performance across all projects."
                    resourceType={{
                        type: 'query_performance',
                        forceIcon: <IconDatabase />,
                    }}
                />
                <p>
                    Only users with staff access can view query performance tooling. Please contact your instance admin.
                </p>
                <p>
                    If you're an admin and don't have access, set <code>is_staff=true</code> for your user on the
                    PostgreSQL <code>posthog_user</code> table.
                </p>
            </>
        )
    }

    const precomputationColumns: LemonTableColumns<PrecomputationTeam> = [
        {
            title: 'Team ID',
            dataIndex: 'team_id',
            width: 100,
        },
        {
            title: 'Team name',
            dataIndex: 'team_name',
        },
        {
            title: 'Organization',
            render: function OrgCell(_, team) {
                return (
                    <div className="flex items-center gap-1">
                        <span>{team.organization_name || <span className="text-muted">Unknown</span>}</span>
                        {team.organization_arr != null && (
                            <LemonTag type="completion">ARR ${team.organization_arr.toLocaleString()}</LemonTag>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Organization ID',
            dataIndex: 'organization_id',
        },
        {
            title: 'Precomputation',
            width: 140,
            render: function PrecomputationToggle(_, team) {
                return (
                    <LemonSwitch
                        checked={team.experiment_precomputation_enabled}
                        onChange={(enabled) => {
                            if (!enabled) {
                                LemonDialog.open({
                                    title: 'Disable precomputation?',
                                    maxWidth: '30rem',
                                    description: `Are you sure you want to disable precomputation for ${
                                        team.team_name || `team ${team.team_id}`
                                    }? Experiment queries will fall back to on-demand execution and may become significantly slower.`,
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Disable precomputation',
                                        onClick: () => setPrecomputation(team.team_id, false),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                                return
                            }
                            setPrecomputation(team.team_id, true)
                        }}
                    />
                )
            },
        },
    ]

    const slowestQueryColumns: LemonTableColumns<SlowestQuery> = [
        {
            title: 'Result',
            width: 220,
            render: function Result(_, item): JSX.Element {
                const { label, type } = outcome(item)
                const tag = <LemonTag type={type}>{label}</LemonTag>
                if (!item.exception) {
                    return tag
                }
                const firstLine = item.exception.split('\n')[0]
                const preview = firstLine.length > 40 ? firstLine.slice(0, 40) + '…' : firstLine
                return (
                    <Tooltip title={<span className="font-mono text-xs whitespace-pre-wrap">{item.exception}</span>}>
                        <div className="flex items-center gap-1 min-w-0">
                            {tag}
                            <span className="font-mono text-xs text-danger truncate">{preview}</span>
                        </div>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Time',
            width: 120,
            render: function Timestamp(_, item): JSX.Element {
                return (
                    <Tooltip title={item.timestamp}>
                        <span className="font-mono text-xs whitespace-nowrap">
                            {dayjs(item.timestamp).format('MMM D HH:mm:ss')}
                        </span>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Duration (ms)',
            width: 150,
            render: function Duration(_, item) {
                // Headline is the total the user waited for (precompute builds + read); the read on its own
                // is shown alongside when this query had sub-queries.
                const total = Math.round(item.total_duration_ms ?? item.execution_time)
                const hasSubQueries = item.sub_queries && item.sub_queries.length > 0
                return (
                    <div className="font-mono">
                        <span>{total}</span>
                        {hasSubQueries && (
                            <span className="text-muted text-xs"> · read {Math.round(item.execution_time)}</span>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Read',
            key: 'read_bytes',
            width: 130,
            sorter: (a, b) => groupBytes(a) - groupBytes(b),
            render: function Read(_, item): JSX.Element {
                const total = groupBytes(item)
                const hasSubQueries = item.sub_queries && item.sub_queries.length > 0
                return (
                    <div className="font-mono">
                        <span>{humanizeBytes(total)}</span>
                        {hasSubQueries && (
                            <span className="text-muted text-xs"> · read {humanizeBytes(item.read_bytes)}</span>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Scan window',
            width: 110,
            render: function ScanWindowCol(_, item): JSX.Element | null {
                return <ScanWindow from={item.experiment_scan_date_from} to={item.experiment_scan_date_to} />
            },
        },
        {
            title: 'Organization',
            render: function OrgCell(_, item) {
                return (
                    <div className="flex items-center gap-1">
                        <span>{item.organization_name || <span className="text-muted">Unknown</span>}</span>
                        {item.organization_arr != null && (
                            <LemonTag type="completion">ARR ${item.organization_arr.toLocaleString()}</LemonTag>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Team ID',
            dataIndex: 'team_id',
            width: 80,
        },
        {
            title: 'Experiment',
            render: function ExperimentCell(_, item): JSX.Element {
                if (!item.experiment_name) {
                    return <span className="text-muted">Unknown</span>
                }
                const label = (
                    <span className="truncate max-w-40 inline-block align-bottom">{item.experiment_name}</span>
                )
                const content =
                    item.experiment_id && item.team_id ? (
                        <Link
                            to={`/project/${item.team_id}/experiments/${item.experiment_id}`}
                            target="_blank"
                            className="truncate max-w-40 inline-block align-bottom"
                        >
                            {item.experiment_name}
                        </Link>
                    ) : (
                        label
                    )
                return <Tooltip title={item.experiment_name}>{content}</Tooltip>
            },
        },
        {
            title: 'Metric',
            render: function Metric(_, item): JSX.Element {
                const metricTypeLabel =
                    item.experiment_metric_type === 'funnel' && item.experiment_funnel_order_type
                        ? `funnel:${item.experiment_funnel_order_type}`
                        : item.experiment_metric_type
                return (
                    <div className="flex items-center gap-1 min-w-0">
                        <Tooltip title={item.experiment_metric_name}>
                            <span className="truncate max-w-40">{item.experiment_metric_name}</span>
                        </Tooltip>
                        {item.experiment_metric_type && <LemonTag type="muted">{metricTypeLabel}</LemonTag>}
                    </div>
                )
            },
        },
        {
            title: 'Path',
            width: 200,
            render: function Path(_, item) {
                if (item.experiment_query_surface === 'precompute_build') {
                    return (
                        <LemonTag type="warning">
                            build{item.experiment_precompute_table ? `: ${item.experiment_precompute_table}` : ''}
                        </LemonTag>
                    )
                }
                const pathTag = (
                    label: string,
                    value: string,
                    table: 'exposures' | 'metric_events'
                ): JSX.Element | null => {
                    if (!value || value === 'not_applicable') {
                        return null
                    }
                    if (value === 'precomputed') {
                        return <LemonTag type="success">{label}: precomputed</LemonTag>
                    }
                    return (
                        <Tooltip title={reasonForDirect(item, table)}>
                            <LemonTag type="default">{label}: direct</LemonTag>
                        </Tooltip>
                    )
                }
                // Fall back to the deprecated experiment_execution_path for rows logged before the split.
                const exposures = pathTag(
                    'exposures',
                    item.experiment_exposures_path || item.experiment_execution_path,
                    'exposures'
                )
                const events = pathTag('events', item.experiment_metric_events_path, 'metric_events')
                if (!exposures && !events) {
                    return null
                }
                return (
                    <div className="flex flex-wrap gap-1">
                        {exposures}
                        {events}
                    </div>
                )
            },
        },
    ]

    const subQueryColumns: LemonTableColumns<SlowestQuery> = [
        {
            title: 'Build',
            width: 180,
            render: function SubQueryBuild(_, item) {
                return <LemonTag type="warning">build: {item.experiment_precompute_table || 'unknown'}</LemonTag>
            },
        },
        {
            title: 'Duration (ms)',
            width: 120,
            render: function SubQueryDuration(_, item) {
                return <span className="font-mono">{Math.round(item.execution_time)}</span>
            },
        },
        {
            title: 'Scan window',
            width: 110,
            render: function SubQueryWindow(_, item): JSX.Element | null {
                return <ScanWindow from={item.precompute_window_start} to={item.precompute_window_end} />
            },
        },
        {
            title: 'Read',
            width: 110,
            render: function SubQueryRead(_, item): JSX.Element {
                return <span className="font-mono">{humanizeBytes(item.read_bytes)}</span>
            },
        },
        {
            title: 'Status',
            render: function SubQueryStatus(_, item) {
                if (!item.exception) {
                    return <LemonTag type="success">OK</LemonTag>
                }
                const firstLine = item.exception.split('\n')[0]
                const preview = firstLine.length > 60 ? firstLine.slice(0, 60) + '…' : firstLine
                return (
                    <div className="flex items-center gap-1 min-w-0">
                        <LemonTag type="danger">Error</LemonTag>
                        <span className="font-mono text-xs text-danger truncate">{preview}</span>
                    </div>
                )
            },
        },
    ]

    return (
        <SceneContent className="mt-4 pb-8">
            <SceneTitleSection
                name="Query performance"
                description="Internal tooling for monitoring and managing query performance across all projects."
                resourceType={{
                    type: 'query_performance',
                    forceIcon: <IconDatabase />,
                }}
            />

            <LemonTabs
                activeKey="experiments"
                tabs={[
                    {
                        key: 'experiments',
                        label: 'Experiments',
                        content: (
                            <>
                                <h2>Slowest queries</h2>
                                <div className="flex flex-wrap gap-2 mb-4 items-center">
                                    {TIME_RANGE_OPTIONS.map(({ label, hours }) => (
                                        <LemonButton
                                            key={hours}
                                            type={hoursBack === hours ? 'primary' : 'tertiary'}
                                            size="small"
                                            onClick={() => setHoursBack(hours)}
                                        >
                                            {label}
                                        </LemonButton>
                                    ))}
                                    <LemonInput
                                        type="number"
                                        min={1}
                                        size="small"
                                        placeholder="Team ID"
                                        value={teamIdFilter ? Number(teamIdFilter) : undefined}
                                        onChange={(value) => setTeamIdFilter(value != null ? String(value) : '')}
                                        className="w-32"
                                    />
                                    <LemonInput
                                        type="number"
                                        min={1}
                                        size="small"
                                        placeholder="Experiment ID"
                                        value={experimentIdFilter ? Number(experimentIdFilter) : undefined}
                                        onChange={(value) => setExperimentIdFilter(value != null ? String(value) : '')}
                                        className="w-36"
                                    />
                                    <LemonSelect
                                        size="small"
                                        value={metricTypeFilter}
                                        onChange={(value) => setMetricTypeFilter(value ?? '')}
                                        options={METRIC_TYPE_OPTIONS}
                                        className="w-44"
                                    />
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => loadSlowestQueries()}
                                        disabledReason={slowestQueriesLoading ? 'Loading...' : undefined}
                                    >
                                        Refresh
                                    </LemonButton>
                                </div>
                                <LemonTable
                                    columns={slowestQueryColumns}
                                    dataSource={slowestQueries}
                                    loading={slowestQueriesLoading}
                                    emptyState="No queries found in this time range"
                                    pagination={{ pageSize: 20 }}
                                    className="overflow-visible! flex-none!"
                                    expandable={{
                                        expandedRowRender: function ExpandedQuery(item) {
                                            return (
                                                <div className="flex flex-col gap-2 p-2">
                                                    <QueryStats {...item} />
                                                    <div className="font-mono text-xs text-muted flex flex-wrap items-center gap-x-3 gap-y-1">
                                                        <span>
                                                            query_id:{' '}
                                                            <CopyToClipboardInline description="query ID">
                                                                {item.query_id}
                                                            </CopyToClipboardInline>
                                                        </span>
                                                        {item.experiment_query_group_id && (
                                                            <span>
                                                                group:{' '}
                                                                <CopyToClipboardInline description="group ID">
                                                                    {item.experiment_query_group_id}
                                                                </CopyToClipboardInline>
                                                            </span>
                                                        )}
                                                        <LinkMetabaseQuery queryId={item.query_id} />
                                                    </div>
                                                    {item.sub_queries && item.sub_queries.length > 0 && (
                                                        <div>
                                                            <h4 className="mb-1">Sub-queries (precompute builds)</h4>
                                                            <LemonTable
                                                                size="small"
                                                                columns={subQueryColumns}
                                                                dataSource={item.sub_queries}
                                                                expandable={{
                                                                    expandedRowRender: function ExpandedSubQuery(sub) {
                                                                        return (
                                                                            <div className="flex flex-col gap-2 p-2">
                                                                                <QueryStats {...sub} />
                                                                                <CodeSnippet
                                                                                    language={Language.SQL}
                                                                                    thing="query"
                                                                                    maxLinesWithoutExpansion={10}
                                                                                >
                                                                                    {sub.query}
                                                                                </CodeSnippet>
                                                                            </div>
                                                                        )
                                                                    },
                                                                }}
                                                            />
                                                        </div>
                                                    )}
                                                    {item.exception && (
                                                        <CodeSnippet
                                                            language={Language.Text}
                                                            thing="error"
                                                            maxLinesWithoutExpansion={5}
                                                        >
                                                            {item.exception}
                                                        </CodeSnippet>
                                                    )}
                                                    <CodeSnippet
                                                        language={Language.SQL}
                                                        thing="query"
                                                        maxLinesWithoutExpansion={10}
                                                    >
                                                        {item.query}
                                                    </CodeSnippet>
                                                </div>
                                            )
                                        },
                                    }}
                                />

                                <h2 className="mt-8">Precomputation</h2>
                                <LemonInput
                                    type="search"
                                    placeholder="Search by organization name..."
                                    value={search}
                                    onChange={setSearch}
                                    className="mb-4 max-w-md"
                                />
                                <LemonTable
                                    columns={precomputationColumns}
                                    dataSource={precomputationTeams}
                                    loading={precomputationTeamsLoading}
                                    emptyState={search ? 'No teams found' : 'No teams have precomputation enabled'}
                                    pagination={{ pageSize: 20 }}
                                    className="overflow-visible! flex-none!"
                                />
                            </>
                        ),
                    },
                ]}
            />
        </SceneContent>
    )
}
