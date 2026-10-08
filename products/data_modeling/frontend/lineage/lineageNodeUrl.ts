import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

type NodeDetailTab = Parameters<typeof urls.nodeDetail>[1]

/** Where clicking a lineage node takes you: a metric to its catalog page, anything else to its node. */
export function lineageNodeUrl(node: Pick<DataModelingNode, 'id' | 'name' | 'type'>, tab?: NodeDetailTab): string {
    if (node.type === 'metric') {
        return urls.dataCatalogMetric(node.name)
    }
    return urls.nodeDetail(node.id, tab)
}
