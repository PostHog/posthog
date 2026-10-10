import { urls } from 'scenes/urls'

import { DataModelingNode, InsightShortId } from '~/types'

type NodeDetailTab = Parameters<typeof urls.nodeDetail>[1]

/**
 * Where clicking a lineage node takes you: a metric to its catalog page, an insight to the insight,
 * anything else to its node.
 */
export function lineageNodeUrl(
    node: Pick<DataModelingNode, 'id' | 'name' | 'type' | 'insight_short_id'>,
    tab?: NodeDetailTab
): string {
    if (node.type === 'metric') {
        return urls.dataCatalogMetric(node.name)
    }
    if (node.type === 'insight' && node.insight_short_id) {
        return urls.insightView(node.insight_short_id as InsightShortId)
    }
    return urls.nodeDetail(node.id, tab)
}
