import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ClusterItemsTable } from './ClusterItemsTable'
import { clustersLogic } from './clustersLogic'
import type { Cluster } from './types'

export function ClusterMemberTable({ cluster }: { cluster: Cluster }): JSX.Element {
    const { clusteringLevel, traceSummaries, traceSummariesLoading, itemMetrics, effectiveRunId } =
        useValues(clustersLogic)
    const rows = Object.entries(cluster.traces)
        .sort(([, a], [, b]) => a.rank - b.rank)
        .slice(0, 20)
        .map(([traceId, traceInfo]) => ({ traceId, traceInfo, summary: traceSummaries[traceId] }))

    return (
        <div className="p-2">
            <ClusterItemsTable
                rows={rows}
                clusteringLevel={clusteringLevel}
                itemMetrics={itemMetrics}
                loading={traceSummariesLoading && !Object.keys(traceSummaries).length}
                listId="clusters"
            />
            <div className="flex items-center justify-between mt-2 text-xs text-muted">
                <span>
                    {rows.length < cluster.size ? `Showing ${rows.length} of ${cluster.size}` : `${cluster.size} items`}
                </span>
                <LemonButton
                    size="xsmall"
                    to={urls.aiObservabilityCluster(effectiveRunId || '', cluster.cluster_id)}
                    data-attr="clusters-view-all-link"
                >
                    View cluster details
                </LemonButton>
            </div>
        </div>
    )
}
