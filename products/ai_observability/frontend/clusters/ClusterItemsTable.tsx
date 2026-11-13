import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { useTraceDrawerRows } from '../redesign/trace/TraceDrawerRowsHost'
import { formatLLMCost, formatLLMLatency } from '../utils'
import type { TraceWithSummary } from './clusterDetailLogic'
import type { ItemMetrics } from './clusterMetricsLoader'
import { toClusterTraceDrawerRow } from './clusterTraceDrawerRow'
import { formatEvalTitle } from './traceSummaryLoader'
import type { ClusteringLevel } from './types'

export function ClusterItemsTable({
    rows,
    clusteringLevel,
    itemMetrics,
    loading,
    listId,
}: {
    rows: TraceWithSummary[]
    clusteringLevel: ClusteringLevel
    itemMetrics: Record<string, ItemMetrics>
    loading: boolean
    listId: 'clusters' | 'cluster-traces'
}): JSX.Element {
    const { rowProps } = useTraceDrawerRows(listId, 'a[data-attr="clusters-view-trace-link"]')
    const itemLabel =
        clusteringLevel === 'evaluation' ? 'Evaluation' : clusteringLevel === 'generation' ? 'Generation' : 'Trace'

    return (
        <LemonTable
            size="small"
            embedded
            dataSource={rows}
            rowKey="traceId"
            loading={loading}
            onRow={(row) => rowProps(toClusterTraceDrawerRow(row, clusteringLevel))}
            columns={[
                {
                    title: itemLabel,
                    key: 'title',
                    render: (_, row) => {
                        const target = toClusterTraceDrawerRow(row, clusteringLevel)
                        const title =
                            clusteringLevel === 'evaluation' ? formatEvalTitle(row.summary, 120) : row.summary?.title
                        return (
                            <div className="flex items-center gap-2">
                                <span className="text-muted tabular-nums">{row.traceInfo.rank + 1}.</span>
                                <div className="min-w-0">
                                    {target ? (
                                        <Link
                                            className="block"
                                            to={urls.aiObservabilityTrace(target.traceId, {
                                                tab: 'thread',
                                                ...(target.timestamp ? { timestamp: target.timestamp } : {}),
                                                ...(target.stepId ? { event: target.stepId } : {}),
                                            })}
                                            data-attr="clusters-view-trace-link"
                                        >
                                            {title || `${itemLabel} ${row.traceId.slice(0, 8)}`}
                                        </Link>
                                    ) : (
                                        <span>{title || 'Loading evaluation…'}</span>
                                    )}
                                </div>
                                {itemMetrics[row.traceId]?.errorCount > 0 && (
                                    <LemonTag type="danger" size="small">
                                        Error
                                    </LemonTag>
                                )}
                                {row.summary?.evaluationVerdict && (
                                    <LemonTag
                                        type={
                                            row.summary.evaluationVerdict === 'fail'
                                                ? 'danger'
                                                : row.summary.evaluationVerdict === 'pass'
                                                  ? 'success'
                                                  : 'muted'
                                        }
                                        size="small"
                                    >
                                        {row.summary.evaluationVerdict}
                                    </LemonTag>
                                )}
                            </div>
                        )
                    },
                },
                {
                    title: 'Time',
                    key: 'time',
                    render: (_, row) => (
                        <span className="text-xs text-muted whitespace-nowrap">
                            {row.traceInfo.timestamp ? <TZLabel time={row.traceInfo.timestamp} /> : '—'}
                        </span>
                    ),
                },
                {
                    title: 'Cost',
                    key: 'cost',
                    align: 'right',
                    render: (_, row) =>
                        itemMetrics[row.traceId]?.cost != null ? formatLLMCost(itemMetrics[row.traceId].cost!) : '—',
                },
                {
                    title: 'Latency',
                    key: 'latency',
                    align: 'right',
                    render: (_, row) =>
                        itemMetrics[row.traceId]?.latency != null
                            ? formatLLMLatency(itemMetrics[row.traceId].latency!)
                            : '—',
                },
            ]}
        />
    )
}
