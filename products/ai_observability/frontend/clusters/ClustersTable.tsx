import { useActions, useValues } from 'kea'

import { LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { urls } from 'scenes/urls'

import { formatErrorRate, formatLLMCost, formatLLMLatency } from '../utils'
import { ClusterMemberTable } from './ClusterMemberTable'
import { clustersLogic } from './clustersLogic'
import { NOISE_CLUSTER_ID, OUTLIER_COLOR } from './constants'
import type { Cluster } from './types'

export function ClustersTable(): JSX.Element {
    const { filteredSortedClusters, currentRun, expandedClusterIds, clusterMetrics, clusteringLevel, effectiveRunId } =
        useValues(clustersLogic)
    const { toggleClusterExpanded, setHoveredClusterId } = useActions(clustersLogic)
    return (
        <div onMouseLeave={() => setHoveredClusterId(null)}>
            <LemonTable<Cluster>
                size="small"
                dataSource={filteredSortedClusters}
                rowKey="cluster_id"
                expandable={{
                    isRowExpanded: (cluster) => expandedClusterIds.has(cluster.cluster_id),
                    onRowExpand: (cluster) => toggleClusterExpanded(cluster.cluster_id),
                    onRowCollapse: (cluster) => toggleClusterExpanded(cluster.cluster_id),
                    expandedRowRender: (cluster) => <ClusterMemberTable cluster={cluster} />,
                }}
                onRow={(cluster) => ({
                    onMouseEnter: () => setHoveredClusterId(cluster.cluster_id),
                    onMouseLeave: () => setHoveredClusterId(null),
                    'data-attr': 'clusters-card-header',
                })}
                columns={[
                    {
                        title: 'Cluster',
                        key: 'cluster',
                        render: (_, cluster) => (
                            <div className="flex gap-2 items-start min-w-48 py-1">
                                <span
                                    className="w-2 h-2 mt-1.5 rounded-full shrink-0"
                                    style={{
                                        backgroundColor:
                                            cluster.cluster_id === NOISE_CLUSTER_ID
                                                ? OUTLIER_COLOR
                                                : getSeriesColor(cluster.cluster_id),
                                    }}
                                />
                                <div className="min-w-0">
                                    <Link
                                        className="block font-semibold"
                                        to={urls.aiObservabilityCluster(effectiveRunId || '', cluster.cluster_id)}
                                        data-attr="clusters-card-title-link"
                                    >
                                        {cluster.title}
                                    </Link>
                                    <Tooltip title={cluster.description}>
                                        <div className="text-xs text-muted line-clamp-1">{cluster.description}</div>
                                    </Tooltip>
                                </div>
                            </div>
                        ),
                    },
                    {
                        title: 'Count',
                        key: 'size',
                        align: 'right',
                        sorter: (a, b) => a.size - b.size,
                        render: (_, cluster) => (
                            <div className="tabular-nums">
                                <div>{cluster.size.toLocaleString()}</div>
                                <div className="text-xs text-muted">
                                    {Math.round((100 * cluster.size) / (currentRun?.totalItemsAnalyzed || 1))}%
                                </div>
                            </div>
                        ),
                    },
                    {
                        title: 'Avg. cost',
                        key: 'cost',
                        align: 'right',
                        sorter: (a, b) =>
                            (clusterMetrics[a.cluster_id]?.avgCost ?? -1) -
                            (clusterMetrics[b.cluster_id]?.avgCost ?? -1),
                        render: (_, cluster) => {
                            const value = clusterMetrics[cluster.cluster_id]?.avgCost
                            return value != null ? formatLLMCost(value) : '—'
                        },
                    },
                    {
                        title: 'Avg. latency',
                        key: 'latency',
                        align: 'right',
                        sorter: (a, b) =>
                            (clusterMetrics[a.cluster_id]?.avgLatency ?? -1) -
                            (clusterMetrics[b.cluster_id]?.avgLatency ?? -1),
                        render: (_, cluster) => {
                            const value = clusterMetrics[cluster.cluster_id]?.avgLatency
                            return value != null ? formatLLMLatency(value) : '—'
                        },
                    },
                    {
                        title: clusteringLevel === 'evaluation' ? 'Pass rate' : 'Errors',
                        key: 'errors',
                        align: 'right',
                        render: (_, cluster) => {
                            const metrics = clusterMetrics[cluster.cluster_id]
                            const value = clusteringLevel === 'evaluation' ? metrics?.passRate : metrics?.errorRate
                            return value != null ? (
                                <LemonTag
                                    type={clusteringLevel !== 'evaluation' && value > 0 ? 'danger' : 'muted'}
                                    size="small"
                                >
                                    {formatErrorRate(value)}
                                </LemonTag>
                            ) : (
                                '—'
                            )
                        },
                    },
                ]}
            />
        </div>
    )
}
