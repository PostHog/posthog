import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    BatchExportApi,
    BatchExportBackfillApi,
    BatchExportRequestApi,
    BatchExportRunApi,
    BatchExportsBackfillsListParams,
    BatchExportsListParams,
    BatchExportsLogsRetrieveParams,
    BatchExportsRunsListParams,
    BatchExportsRunsLogsRetrieveParams,
    CreateFileDownloadRequestApi,
    CreateOutputApi,
    FileDownloadBatchExportOnDemandApi,
    FileDownloadBatchExportsLogsRetrieveParams,
    PaginatedBatchExportBackfillListApi,
    PaginatedBatchExportListApi,
    PaginatedBatchExportRunListApi,
    PatchedBatchExportRequestApi,
    RetrieveFileDownloadResponseApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getBatchExportsListUrl = (projectId: string, params?: BatchExportsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/batch_exports/?${stringifiedParams}`
        : `/api/projects/${projectId}/batch_exports/`
}

export const batchExportsList = async (
    projectId: string,
    params?: BatchExportsListParams,
    options?: RequestInit
): Promise<PaginatedBatchExportListApi> => {
    return apiMutator<PaginatedBatchExportListApi>(getBatchExportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/`
}

export const batchExportsCreate = async (
    projectId: string,
    batchExportRequestApi: BatchExportRequestApi,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportRequestApi),
    })
}

export const getBatchExportsBackfillsListUrl = (
    projectId: string,
    batchExportId: string,
    params?: BatchExportsBackfillsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/?${stringifiedParams}`
        : `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/`
}

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export const batchExportsBackfillsList = async (
    projectId: string,
    batchExportId: string,
    params?: BatchExportsBackfillsListParams,
    options?: RequestInit
): Promise<PaginatedBatchExportBackfillListApi> => {
    return apiMutator<PaginatedBatchExportBackfillListApi>(
        getBatchExportsBackfillsListUrl(projectId, batchExportId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getBatchExportsBackfillsCreateUrl = (projectId: string, batchExportId: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/`
}

/**
 * Create a new backfill for a BatchExport.
 */
export const batchExportsBackfillsCreate = async (
    projectId: string,
    batchExportId: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<BatchExportBackfillApi> => {
    return apiMutator<BatchExportBackfillApi>(getBatchExportsBackfillsCreateUrl(projectId, batchExportId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportBackfillApi),
    })
}

export const getBatchExportsBackfillsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/${id}/`
}

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export const batchExportsBackfillsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportBackfillApi> => {
    return apiMutator<BatchExportBackfillApi>(getBatchExportsBackfillsRetrieveUrl(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsBackfillsCancelCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/${id}/cancel/`
}

/**
 * Cancel a batch export backfill.
 */
export const batchExportsBackfillsCancelCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsBackfillsCancelCreateUrl(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportBackfillApi),
    })
}

export const getBatchExportsRunsListUrl = (
    projectId: string,
    batchExportId: string,
    params?: BatchExportsRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/`
}

export const batchExportsRunsList = async (
    projectId: string,
    batchExportId: string,
    params?: BatchExportsRunsListParams,
    options?: RequestInit
): Promise<PaginatedBatchExportRunListApi> => {
    return apiMutator<PaginatedBatchExportRunListApi>(getBatchExportsRunsListUrl(projectId, batchExportId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsRunsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/`
}

export const batchExportsRunsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportRunApi> => {
    return apiMutator<BatchExportRunApi>(getBatchExportsRunsRetrieveUrl(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsRunsCancelCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/cancel/`
}

/**
 * Cancel a batch export run.
 */
export const batchExportsRunsCancelCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunsCancelCreateUrl(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportRunApi),
    })
}

export const getBatchExportsRunsLogsRetrieveUrl = (
    projectId: string,
    batchExportId: string,
    id: string,
    params?: BatchExportsRunsLogsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/`
}

export const batchExportsRunsLogsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    params?: BatchExportsRunsLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunsLogsRetrieveUrl(projectId, batchExportId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsRunsRetryCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
}

/**
 * Retry a batch export run.

We use the same underlying mechanism as when backfilling a batch export, as retrying
a run is the same as backfilling one run.
 */
export const batchExportsRunsRetryCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunsRetryCreateUrl(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportRunApi),
    })
}

export const getBatchExportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsUpdate = async (
    projectId: string,
    id: string,
    batchExportRequestApi: BatchExportRequestApi,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportRequestApi),
    })
}

export const getBatchExportsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedBatchExportRequestApi?: PatchedBatchExportRequestApi,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportRequestApi),
    })
}

export const getBatchExportsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getBatchExportsLogsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: BatchExportsLogsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/batch_exports/${id}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve = async (
    projectId: string,
    id: string,
    params?: BatchExportsLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsLogsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/pause/`
}

/**
 * Pause a BatchExport.
 */
export const batchExportsPauseCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsPauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsUnpauseCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/unpause/`
}

/**
 * Unpause a BatchExport.
 */
export const batchExportsUnpauseCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsUnpauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepNewCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepNewCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsTestRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/test/`
}

export const batchExportsTestRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsTestRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getFileDownloadBatchExportsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_download_batch_exports/`
}

/**
 * Create and start a batch export on demand run to download a file.
 */
export const fileDownloadBatchExportsCreate = async (
    projectId: string,
    createFileDownloadRequestApi?: CreateFileDownloadRequestApi,
    options?: RequestInit
): Promise<CreateOutputApi> => {
    return apiMutator<CreateOutputApi>(getFileDownloadBatchExportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createFileDownloadRequestApi),
    })
}

export const getFileDownloadBatchExportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_download_batch_exports/${id}/`
}

/**
 * Get a run of a batch export on demand.

If the underlying batch export run has completed, we return keys to the
generated file downloads so that users may download them by making a request
to /download.
 */
export const fileDownloadBatchExportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RetrieveFileDownloadResponseApi> => {
    return apiMutator<RetrieveFileDownloadResponseApi>(getFileDownloadBatchExportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFileDownloadBatchExportsCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_download_batch_exports/${id}/cancel/`
}

/**
 * Cancel an ongoing file-download batch export.
 */
export const fileDownloadBatchExportsCancelCreate = async (
    projectId: string,
    id: string,
    fileDownloadBatchExportOnDemandApi: FileDownloadBatchExportOnDemandApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileDownloadBatchExportsCancelCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileDownloadBatchExportOnDemandApi),
    })
}

export const getFileDownloadBatchExportsDownloadRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_download_batch_exports/${id}/download/`
}

/**
 * Download a file (or a part) from this batch export run.

Users can provide a part component with an id or index, or no part component at
all:
* If part id is included: The file download matching the id is downloaded.
* If part index is included: The file download matching the index (as ordered
    by key) is downloaded.
* If no part component is present: If there is only one file downloaded, that
    is downloaded. Otherwise the first one as sorted by key is downloaded.
 */
export const fileDownloadBatchExportsDownloadRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileDownloadBatchExportsDownloadRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFileDownloadBatchExportsLogsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: FileDownloadBatchExportsLogsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/file_download_batch_exports/${id}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/file_download_batch_exports/${id}/logs/`
}

export const fileDownloadBatchExportsLogsRetrieve = async (
    projectId: string,
    id: string,
    params?: FileDownloadBatchExportsLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileDownloadBatchExportsLogsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}
