import { urls } from 'scenes/urls'

import { subjectDetailUrl } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { nodeEndpointModel, nodeEndpointUrl } from './endpointModelName'
import type { AttentionSubject } from './modelsOverviewLogic'

export function subjectHref(subject: AttentionSubject): string | null {
    const { node, materialization, failingChecks } = subject
    if (node && nodeEndpointModel(node)) {
        return nodeEndpointUrl(node)
    }
    if (node) {
        return urls.nodeDetail(node.id, materialization ? 'materialization' : 'data-quality')
    }
    const [check] = failingChecks
    return check ? subjectDetailUrl(check) : null
}
