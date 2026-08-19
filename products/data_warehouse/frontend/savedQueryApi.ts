import { ApiConfig, CountedPaginatedResponse } from 'lib/api'

import { DataModelingJob, DataWarehouseSavedQueryDependencies, DataWarehouseSavedQueryRunHistory } from '~/types'

import {
    dataModelingJobsList,
    warehouseSavedQueriesCancelCreate,
    warehouseSavedQueriesDependenciesRetrieve,
    warehouseSavedQueriesRevertMaterializationCreate,
    warehouseSavedQueriesRunHistoryRetrieve,
} from './generated/api'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const savedQueryApi = {
    async cancel(viewId: string): Promise<void> {
        await warehouseSavedQueriesCancelCreate(
            projectId(),
            viewId,
            {} as Parameters<typeof warehouseSavedQueriesCancelCreate>[2]
        )
    },
    async revertMaterialization(viewId: string): Promise<void> {
        await warehouseSavedQueriesRevertMaterializationCreate(
            projectId(),
            viewId,
            {} as Parameters<typeof warehouseSavedQueriesRevertMaterializationCreate>[2]
        )
    },
    async dependencies(viewId: string): Promise<DataWarehouseSavedQueryDependencies> {
        return (await warehouseSavedQueriesDependenciesRetrieve(
            projectId(),
            viewId
        )) as unknown as DataWarehouseSavedQueryDependencies
    },
    async runHistory(viewId: string): Promise<{ run_history: DataWarehouseSavedQueryRunHistory[] }> {
        return (await warehouseSavedQueriesRunHistoryRetrieve(projectId(), viewId)) as unknown as {
            run_history: DataWarehouseSavedQueryRunHistory[]
        }
    },
    dataWarehouseDataModelingJobs: {
        async list(
            savedQueryId: string,
            pageSize: number,
            offset: number
        ): Promise<CountedPaginatedResponse<DataModelingJob>> {
            return (await dataModelingJobsList(projectId(), {
                saved_query_id: savedQueryId,
                limit: pageSize,
                offset,
            })) as unknown as CountedPaginatedResponse<DataModelingJob>
        },
    },
}
