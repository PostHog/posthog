import { PaginatedResponse } from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { DataWarehouseManagedViewsetKind } from '~/queries/schema/schema-general'
import { DataWarehouseManagedViewsetSavedQuery, DataWarehouseViewLink, DataWarehouseViewLinkValidation } from '~/types'

import { revenueAnalyticsJoinsCreate } from 'products/revenue_analytics/frontend/generated/api'

import {
    getWarehouseViewLinkCreateUrl,
    managedViewsetsRetrieve,
    managedViewsetsUpdate,
    warehouseViewLinkCreate,
    warehouseViewLinkList,
    warehouseViewLinkPartialUpdate,
    warehouseViewLinkValidateCreate,
} from './generated/api'

const projectId = (): string => String(getCurrentTeamId())

export const warehouseViewLinksApi = {
    async list(): Promise<PaginatedResponse<DataWarehouseViewLink>> {
        return (await warehouseViewLinkList(projectId())) as unknown as PaginatedResponse<DataWarehouseViewLink>
    },
    async create(data: Partial<DataWarehouseViewLink>): Promise<DataWarehouseViewLink> {
        return (await warehouseViewLinkCreate(
            projectId(),
            data as Parameters<typeof warehouseViewLinkCreate>[1]
        )) as unknown as DataWarehouseViewLink
    },
    async update(
        viewId: string,
        data: Pick<
            DataWarehouseViewLink,
            'source_table_name' | 'source_table_key' | 'joining_table_name' | 'joining_table_key' | 'field_name'
        >
    ): Promise<DataWarehouseViewLink> {
        return (await warehouseViewLinkPartialUpdate(
            projectId(),
            viewId,
            data as Parameters<typeof warehouseViewLinkPartialUpdate>[2]
        )) as unknown as DataWarehouseViewLink
    },
    async validate(
        data: Pick<
            DataWarehouseViewLink,
            'source_table_name' | 'source_table_key' | 'joining_table_name' | 'joining_table_key'
        >
    ): Promise<DataWarehouseViewLinkValidation> {
        return (await warehouseViewLinkValidateCreate(
            projectId(),
            data as Parameters<typeof warehouseViewLinkValidateCreate>[1]
        )) as unknown as DataWarehouseViewLinkValidation
    },
    determineDeleteEndpoint(): string {
        return getWarehouseViewLinkCreateUrl(projectId())
            .replace(/^\/api\//, '')
            .replace(/\/$/, '')
    },
}

export const managedViewsetsApi = {
    async toggle(kind: DataWarehouseManagedViewsetKind, enabled: boolean): Promise<void> {
        await managedViewsetsUpdate(projectId(), kind, { enabled })
    },
    async getViews(kind: DataWarehouseManagedViewsetKind): Promise<{
        views: DataWarehouseManagedViewsetSavedQuery[]
        count: number
    }> {
        return (await managedViewsetsRetrieve(projectId(), kind)) as unknown as {
            views: DataWarehouseManagedViewsetSavedQuery[]
            count: number
        }
    },
}

export const revenueAnalyticsJoinsApi = {
    async sync(enabled: boolean): Promise<void> {
        await revenueAnalyticsJoinsCreate(projectId(), { enabled })
    },
}
