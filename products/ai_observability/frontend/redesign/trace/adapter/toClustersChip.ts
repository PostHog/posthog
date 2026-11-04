import { urls } from 'scenes/urls'

import type { TraceClusterApi } from '../../../generated/api.schemas'
import { ClusterChipItem, TraceClustersChipProps } from '../components/TraceClustersChip'

function toItem(cluster: TraceClusterApi): ClusterChipItem {
    return {
        label: cluster.title ?? (cluster.isOutlier ? 'Outliers' : `Cluster ${cluster.clusterId}`),
        description: cluster.description,
        jobName: cluster.jobName,
        isOutlier: cluster.isOutlier,
        runAt: cluster.runAt,
        href: urls.aiObservabilityCluster(cluster.runId, cluster.clusterId),
    }
}

export function toClustersChip(clusters: TraceClusterApi[] | null): TraceClustersChipProps | null {
    if (!clusters?.length) {
        return null
    }
    const [first, ...others] = clusters.map(toItem)
    return { first, others }
}
