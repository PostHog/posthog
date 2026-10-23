import { ApiConfig } from 'lib/api'

import { dataCatalogMetricsApproveCreate, dataCatalogMetricsCreate } from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'

export type MetricCreateRequest = Omit<Parameters<typeof dataCatalogMetricsCreate>[1], 'created_source'>

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
