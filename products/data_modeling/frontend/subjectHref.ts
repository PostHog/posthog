import { urls } from 'scenes/urls'

import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'

import { subjectDetailUrl } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { endpointModelUrl, nodeEndpointModel, nodeEndpointUrl } from './endpointModelName'
import type { ModelRow } from './modelsListLogic'
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

export function modelRowHref(row: ModelRow): string {
    const { view, node, materialization, failingChecks } = row
    if (view.origin === DataWarehouseSavedQueryOrigin.ENDPOINT) {
        return endpointModelUrl(view.name)
    }
    if (node) {
        return materialization || failingChecks.length > 0 ? subjectHref(row)! : urls.nodeDetail(node.id)
    }
    return view.managed_viewset_kind !== null
        ? urls.dataWarehouseManagedViewsets()
        : urls.sqlEditor({ view_id: view.id })
}
