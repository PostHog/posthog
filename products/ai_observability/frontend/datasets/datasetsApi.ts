import { ApiConfig } from '~/lib/api'

import {
    datasetItemsArchive,
    datasetItemsCreate,
    datasetItemsList,
    datasetItemsPartialUpdate,
    datasetItemsRestore,
    datasetsArchive,
    datasetsCreate,
    datasetsList,
    datasetsPartialUpdate,
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
    DatasetReadApi,
    DatasetsListParams,
    PaginatedDatasetItemReadListApi,
    PaginatedDatasetReadListApi,
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
}
