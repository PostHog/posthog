import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { summarizeSharingDebug, type DashboardSharingDebugRun } from './summarizeSharingDebug'

export interface DashboardQuerySharingDebugProps {
    dashboardName: string
    run: DashboardSharingDebugRun | null
    summary: ReturnType<typeof summarizeSharingDebug> | null
}

export function DashboardQuerySharingDebug({
    dashboardName,
    run,
    summary,
}: DashboardQuerySharingDebugProps): JSX.Element {
    const executions = Object.values(run?.results ?? {}).flatMap((result) => result.debug?.executions ?? [])

    return (
        <details className="my-3 rounded border bg-surface-primary" data-attr="dashboard-query-sharing-debug">
            <summary className="cursor-pointer p-3 font-semibold" data-attr="dashboard-query-sharing-debug-toggle">
                Query sharing debug
                {summary && run?.status !== 'skipped' && (
                    <span className="ml-2 font-normal text-secondary">
                        {summary.sharedGroups} shared {summary.sharedGroups === 1 ? 'group' : 'groups'}
                        {' · '}
                        {summary.cachedTiles} cached {summary.cachedTiles === 1 ? 'tile' : 'tiles'}
                        {' · '}
                        {run?.status}
                    </span>
                )}
            </summary>
            <div className="border-t p-3 space-y-3 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold break-words min-w-0">{dashboardName}</span>
                    <LemonTag type="warning">Experimental</LemonTag>
                </div>
                <p className="text-secondary mb-0">
                    Sharing happens between tiles in this dashboard refresh, not across dashboards. Diagnostics stay in
                    this page session.
                </p>
                {!run ? (
                    <p className="mb-0">
                        Refresh the dashboard to inspect sharing. Use a forced refresh to bypass cached results.
                    </p>
                ) : run.status === 'skipped' ? (
                    <p className="mb-0">{run.reason}</p>
                ) : (
                    <>
                        <div className="flex flex-wrap gap-x-6 gap-y-2" aria-live="polite">
                            <span>
                                <strong>{summary?.queryCount.toLocaleString()}</strong> measured ClickHouse queries
                            </span>
                            <span>
                                <strong>{summary?.rowsRead.toLocaleString()}</strong> rows read
                            </span>
                            <span>
                                <strong>{((summary?.durationMs ?? 0) / 1000).toFixed(3)} s</strong> summed query time
                            </span>
                            <span>
                                <strong>
                                    {summary?.receivedTiles}/{run.tiles.length}
                                </strong>{' '}
                                tile responses
                            </span>
                        </div>
                        {summary && summary.sharedGroups > 0 && (
                            <p className="mb-0">
                                {summary.combinedQueries} query consumers combined into {summary.sharedGroups} shared{' '}
                                {summary.sharedGroups === 1 ? 'execution' : 'executions'}.
                            </p>
                        )}
                        {run.status === 'running' && (
                            <p className="mb-0">Refresh in progress. Totals update as tiles finish.</p>
                        )}
                        {(run.status === 'partial' || run.status === 'aborted') && (
                            <p className="text-warning mb-0">
                                {run.status === 'aborted'
                                    ? 'Refresh cancelled.'
                                    : 'Some tiles used the normal retry path.'}{' '}
                                These totals are partial; unfinished work and normal-path retries are not included.
                            </p>
                        )}
                        {summary?.truncated && (
                            <p className="text-warning mb-0">
                                Some execution details were truncated. Work totals are still included.
                            </p>
                        )}
                        <LemonTable
                            size="small"
                            rowKey="id"
                            dataSource={run.tiles}
                            columns={[
                                {
                                    title: 'Tile',
                                    key: 'tile',
                                    render: (_, tile) => <span className="break-words">{tile.name}</span>,
                                },
                                {
                                    title: 'Execution',
                                    key: 'execution',
                                    render: (_, tile) => {
                                        const result = run.results[tile.id]
                                        const decisions = executions.filter((entry) => entry.tile_ids.includes(tile.id))
                                        if (!result) {
                                            return run.status === 'running'
                                                ? 'Waiting for result…'
                                                : 'No diagnostic result'
                                        }
                                        return (
                                            <div className="space-y-1 whitespace-normal">
                                                {result.failed && <LemonTag type="danger">Tile error</LemonTag>}
                                                {result.cached && <LemonTag type="default">Cache hit</LemonTag>}
                                                {!result.debug && <span>Diagnostics unavailable</span>}
                                                {result.debug && !result.cached && decisions.length === 0 && (
                                                    <span>No sharing decision recorded</span>
                                                )}
                                                {decisions.map((entry, index) => (
                                                    <div key={index}>
                                                        <LemonTag
                                                            type={
                                                                entry.outcome === 'shared'
                                                                    ? 'success'
                                                                    : entry.outcome === 'fallback'
                                                                      ? 'warning'
                                                                      : 'default'
                                                            }
                                                        >
                                                            {entry.outcome === 'shared'
                                                                ? 'Shared'
                                                                : entry.outcome === 'fallback'
                                                                  ? 'Shared attempt failed'
                                                                  : 'Separate'}
                                                        </LemonTag>{' '}
                                                        {entry.rule && <code>{entry.rule}</code>}
                                                        {entry.rule === 'count_fusion' && (
                                                            <div>
                                                                One event scan computes the counts with each query’s
                                                                filters.
                                                            </div>
                                                        )}
                                                        {entry.rule === 'same_aggregation_top_n' && (
                                                            <div>
                                                                One aggregation feeds each query’s ordering and limit.
                                                            </div>
                                                        )}
                                                        {entry.tile_ids.length > 1 && (
                                                            <div className="text-secondary break-words">
                                                                With:{' '}
                                                                {entry.tile_ids
                                                                    .filter((id) => id !== tile.id)
                                                                    .map(
                                                                        (id) =>
                                                                            run.tiles.find(
                                                                                (candidate) => candidate.id === id
                                                                            )?.name ?? `Tile ${id}`
                                                                    )
                                                                    .join(', ')}
                                                            </div>
                                                        )}
                                                        {entry.reason && (
                                                            <div className="text-secondary">{entry.reason}</div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )
                                    },
                                },
                            ]}
                        />
                        <p className="text-secondary text-xs mb-0">
                            Work is counted once, including measured lookups and failed attempts. Query time is summed,
                            not dashboard load time. Older ClickHouse protocols use client round-trip time. Bytes read
                            and baseline savings are not measured. No SQL text or query results are collected by this
                            panel.
                        </p>
                    </>
                )}
            </div>
        </details>
    )
}
