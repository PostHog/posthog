import { getColorVar, getSeriesColor } from 'lib/colors'

import type { ItemMetrics } from './clusterMetricsLoader'
import type { ClusterScatterSeries } from './clusterScatter'
import { NOISE_CLUSTER_ID, OUTLIER_COLOR } from './constants'
import type { Cluster } from './types'

export type ClusterMapSize = 'none' | 'cost' | 'latency'
export type ClusterMapHighlight = 'cluster' | 'errors'

export function buildClusterMapSeries(
    clusters: Cluster[],
    metrics: Record<string, ItemMetrics>,
    sizeBy: ClusterMapSize,
    highlight: ClusterMapHighlight,
    hoveredClusterId: number | null
): ClusterScatterSeries[] {
    const errorColor = highlight === 'errors' ? getColorVar('danger') : ''
    const normalColor = getColorVar('muted')
    const maximum = Math.max(
        0,
        ...clusters.flatMap((cluster) =>
            Object.keys(cluster.traces).map((id) => (sizeBy === 'none' ? 0 : (metrics[id]?.[sizeBy] ?? 0)))
        )
    )
    return clusters.map((cluster) => {
        const color = cluster.cluster_id === NOISE_CLUSTER_ID ? OUTLIER_COLOR : getSeriesColor(cluster.cluster_id)
        const faded = hoveredClusterId !== null && hoveredClusterId !== cluster.cluster_id
        return {
            key: `cluster-${cluster.cluster_id}`,
            label: cluster.title,
            color,
            shape: cluster.cluster_id === NOISE_CLUSTER_ID ? 'cross' : 'circle',
            points: Object.entries(cluster.traces).map(([itemId, info]) => {
                const metric = metrics[itemId]
                const value = sizeBy === 'none' ? null : metric?.[sizeBy]
                const pointColor = highlight === 'errors' ? (metric?.errorCount ? errorColor : normalColor) : color
                return {
                    x: info.x,
                    y: info.y,
                    radius: value != null && value >= 0 && maximum > 0 ? 3 + 7 * Math.sqrt(value / maximum) : 4,
                    color: faded ? `${normalColor}50` : pointColor,
                    meta: {
                        itemId,
                        clusterId: cluster.cluster_id,
                        traceId: info.trace_id || itemId,
                        generationId: info.generation_id,
                        timestamp: info.timestamp,
                        metrics: metric,
                    },
                }
            }),
        }
    })
}
