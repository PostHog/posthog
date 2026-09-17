import { combineUrl, router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import type { NodeDetailSceneTab } from 'scenes/models/nodeDetailSceneLogic'
import { urls } from 'scenes/urls'

import type { DataModelingNode } from '~/types'

export function openModelNode(
    node: Pick<DataModelingNode, 'id' | 'type' | 'endpoint'>,
    tab?: NodeDetailSceneTab,
    replace = false
): void {
    let url: string
    if (node.endpoint) {
        const endpointTab =
            tab === 'tests' ? 'data_quality' : tab === 'materialization' ? 'configuration' : (tab ?? 'lineage')
        url = combineUrl(urls.endpoint(node.endpoint.name, node.endpoint.version), { tab: endpointTab }).url
    } else if (node.type === 'endpoint') {
        lemonToast.info('This model is no longer linked to an endpoint. Choose an endpoint from the list.')
        url = urls.endpoints()
    } else {
        url = urls.nodeDetail(node.id, tab)
    }
    if (replace) {
        router.actions.replace(url)
    } else {
        router.actions.push(url)
    }
}
