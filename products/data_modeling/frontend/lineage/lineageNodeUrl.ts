import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

type NodeDetailTab = Parameters<typeof urls.nodeDetail>[1]

/** Where clicking a lineage node takes you: a metric to its catalog page, a published model to its endpoint version. */
export function lineageNodeUrl(
    node: Pick<DataModelingNode, 'id' | 'name' | 'type' | 'endpoint'>,
    tab?: NodeDetailTab
): string {
    if (node.type === 'metric') {
        return urls.dataCatalogMetric(node.name)
    }
    if (node.endpoint) {
        const endpointTab =
            tab === 'data-quality' ? 'data_quality' : tab === 'materialization' ? 'configuration' : (tab ?? 'lineage')
        return combineUrl(urls.endpoint(node.endpoint.name, node.endpoint.version), { tab: endpointTab }).url
    }
    if (node.type === 'endpoint') {
        return urls.endpoints()
    }
    return urls.nodeDetail(node.id, tab)
}
