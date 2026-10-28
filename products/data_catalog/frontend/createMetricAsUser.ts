import { ApiConfig } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { dataCatalogMetricsApproveCreate, dataCatalogMetricsCreate } from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'

export type MetricCreateRequest = Omit<Parameters<typeof dataCatalogMetricsCreate>[1], 'created_source'>

export interface ToastButton {
    label: string
    action: () => void
}

export type MetricSaveAction = 'approve' | 'propose'

export type CreatedMetricApproval = 'approved' | 'proposed' | 'approval_failed'

export interface CreatedMetric {
    metric: DataCatalogMetricApi
    approval: CreatedMetricApproval
}

export async function createMetricAsUser(request: MetricCreateRequest, approve: boolean): Promise<CreatedMetric> {
    const projectId = String(ApiConfig.getCurrentTeamId())
    const metric = await dataCatalogMetricsCreate(projectId, { ...request, created_source: 'user' })
    if (!approve || request.overwrite) {
        return { metric, approval: 'proposed' }
    }
    try {
        const approved = await dataCatalogMetricsApproveCreate(projectId, metric.name, {
            expected_updated_at: metric.updated_at ?? undefined,
        })
        return { metric: approved, approval: 'approved' }
    } catch {
        return { metric, approval: 'approval_failed' }
    }
}

export function toastCreatedMetric(created: CreatedMetric, overwrite: boolean, button?: ToastButton): void {
    const options = button ? { button } : undefined
    if (overwrite) {
        lemonToast.success('Metric overwritten. It needs approval.', options)
    } else if (created.approval === 'approved') {
        lemonToast.success('Metric created and approved', options)
    } else if (created.approval === 'approval_failed') {
        lemonToast.warning('Metric created, but approving it failed. Approve it from the banner.', options)
    } else {
        lemonToast.success('Metric saved as proposed', options)
    }
}
