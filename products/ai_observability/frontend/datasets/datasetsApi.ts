import { ApiConfig } from '~/lib/api'

import {
    datasetItemsArchive,
    datasetItemsCreate,
    datasetItemsList,
    datasetItemsPartialUpdate,
    datasetItemsRetrieve,
    datasetItemsRestore,
    datasetItemsVersionsList,
    datasetsArchive,
    datasetsCreate,
    datasetsExportsCreate,
    datasetsExportsRetrieve,
    datasetsList,
    datasetsPartialUpdate,
    datasetsRevisionsList,
    datasetsRestore,
    datasetsRetrieve,
} from '../generated/api'
import type {
    DatasetCreateApi,
    DatasetItemArchiveApi,
    DatasetItemCreateApi,
    DatasetItemReadApi,
    DatasetItemRestoreApi,
    DatasetItemsPartialUpdateBody,
    DatasetItemsListParams,
    DatasetItemsRetrieveParams,
    DatasetItemsVersionsListParams,
    DatasetReadApi,
    DatasetExportReadApi,
    DatasetsRevisionsListParams,
    DatasetsListParams,
    PaginatedDatasetItemReadListApi,
    PaginatedDatasetReadListApi,
    PaginatedDatasetRevisionReadListApi,
    PatchedDatasetUpdateApi,
} from '../generated/api.schemas'

function getCurrentProjectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

export const datasetsApi = {
    listDatasets(params?: DatasetsListParams): Promise<PaginatedDatasetReadListApi> {
        return datasetsList(getCurrentProjectId(), params)
    },

    getDataset(id: string): Promise<DatasetReadApi> {
        return datasetsRetrieve(getCurrentProjectId(), id)
    },

    createDataset(data: DatasetCreateApi): Promise<DatasetReadApi> {
        return datasetsCreate(getCurrentProjectId(), data)
    },

    updateDataset(id: string, data: PatchedDatasetUpdateApi): Promise<DatasetReadApi> {
        return datasetsPartialUpdate(getCurrentProjectId(), id, data)
    },

    archiveDataset(id: string): Promise<DatasetReadApi> {
        return datasetsArchive(getCurrentProjectId(), id)
    },

    restoreDataset(id: string): Promise<DatasetReadApi> {
        return datasetsRestore(getCurrentProjectId(), id)
    },

    listItems(params: DatasetItemsListParams): Promise<PaginatedDatasetItemReadListApi> {
        return datasetItemsList(getCurrentProjectId(), params)
    },

    getItem(id: string, revision?: number): Promise<DatasetItemReadApi> {
        const params: DatasetItemsRetrieveParams | undefined = revision === undefined ? undefined : { revision }
        return datasetItemsRetrieve(getCurrentProjectId(), id, params)
    },

    listItemVersions(id: string, params?: DatasetItemsVersionsListParams): Promise<PaginatedDatasetItemReadListApi> {
        return datasetItemsVersionsList(getCurrentProjectId(), id, params)
    },

    listRevisions(id: string, params?: DatasetsRevisionsListParams): Promise<PaginatedDatasetRevisionReadListApi> {
        return datasetsRevisionsList(getCurrentProjectId(), id, params)
    },

    createItem(data: DatasetItemCreateApi): Promise<DatasetItemReadApi> {
        return datasetItemsCreate(getCurrentProjectId(), data)
    },

    updateItem(id: string, data: DatasetItemsPartialUpdateBody): Promise<DatasetItemReadApi> {
        return datasetItemsPartialUpdate(getCurrentProjectId(), id, data)
    },

    archiveItem(id: string, data: DatasetItemArchiveApi): Promise<DatasetItemReadApi> {
        return datasetItemsArchive(getCurrentProjectId(), id, data)
    },

    restoreItem(id: string, data: DatasetItemRestoreApi): Promise<DatasetItemReadApi> {
        return datasetItemsRestore(getCurrentProjectId(), id, data)
    },

    exportDataset(id: string, revision?: number): Promise<DatasetExportReadApi> {
        return datasetsExportsCreate(getCurrentProjectId(), id, revision === undefined ? {} : { revision })
    },

    getExport(id: string, exportId: number): Promise<DatasetExportReadApi> {
        return datasetsExportsRetrieve(getCurrentProjectId(), id, String(exportId))
    },
}
