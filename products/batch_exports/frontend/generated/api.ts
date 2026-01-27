/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    BatchExportApi,
    BatchExportBackfillApi,
    BatchExportRunApi,
    BatchExportsBackfillsListParams,
    BatchExportsList2Params,
    BatchExportsListParams,
    BatchExportsRunsListParams,
    EnvironmentsBatchExportsBackfillsListParams,
    EnvironmentsBatchExportsListParams,
    EnvironmentsBatchExportsRunsListParams,
    PaginatedBatchExportBackfillListApi,
    PaginatedBatchExportListApi,
    PaginatedBatchExportRunListApi,
    PatchedBatchExportApi,
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

export const getEnvironmentsBatchExportsListUrl = (projectId: string, params?: EnvironmentsBatchExportsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/batch_exports/?${stringifiedParams}`
        : `/api/environments/${projectId}/batch_exports/`
}

export const environmentsBatchExportsList = async (
    projectId: string,
    params?: EnvironmentsBatchExportsListParams,
    options?: RequestInit
): Promise<PaginatedBatchExportListApi> => {
    return apiMutator<PaginatedBatchExportListApi>(getEnvironmentsBatchExportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsBatchExportsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/`
}

export const environmentsBatchExportsCreate = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getEnvironmentsBatchExportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export const getEnvironmentsBatchExportsBackfillsListUrl = (
    projectId: string,
    batchExportId: string,
    params?: EnvironmentsBatchExportsBackfillsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/?${stringifiedParams}`
        : `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/`
}

export const environmentsBatchExportsBackfillsList = async (
    projectId: string,
    batchExportId: string,
    params?: EnvironmentsBatchExportsBackfillsListParams,
    options?: RequestInit
): Promise<PaginatedBatchExportBackfillListApi> => {
    return apiMutator<PaginatedBatchExportBackfillListApi>(
        getEnvironmentsBatchExportsBackfillsListUrl(projectId, batchExportId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create a new backfill for a BatchExport.
 */
export const getEnvironmentsBatchExportsBackfillsCreateUrl = (projectId: string, batchExportId: string) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/`
}

export const environmentsBatchExportsBackfillsCreate = async (
    projectId: string,
    batchExportId: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<BatchExportBackfillApi> => {
    return apiMutator<BatchExportBackfillApi>(getEnvironmentsBatchExportsBackfillsCreateUrl(projectId, batchExportId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportBackfillApi),
    })
}

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export const getEnvironmentsBatchExportsBackfillsRetrieveUrl = (
    projectId: string,
    batchExportId: string,
    id: string
) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/${id}/`
}

export const environmentsBatchExportsBackfillsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportBackfillApi> => {
    return apiMutator<BatchExportBackfillApi>(
        getEnvironmentsBatchExportsBackfillsRetrieveUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Cancel a batch export backfill.
 */
export const getEnvironmentsBatchExportsBackfillsCancelCreateUrl = (
    projectId: string,
    batchExportId: string,
    id: string
) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/${id}/cancel/`
}

export const environmentsBatchExportsBackfillsCancelCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsBackfillsCancelCreateUrl(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportBackfillApi),
    })
}

export const getEnvironmentsBatchExportsRunsListUrl = (
    projectId: string,
    batchExportId: string,
    params?: EnvironmentsBatchExportsRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/?${stringifiedParams}`
        : `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/`
}

export const environmentsBatchExportsRunsList = async (
    projectId: string,
    batchExportId: string,
    params?: EnvironmentsBatchExportsRunsListParams,
    options?: RequestInit
): Promise<PaginatedBatchExportRunListApi> => {
    return apiMutator<PaginatedBatchExportRunListApi>(
        getEnvironmentsBatchExportsRunsListUrl(projectId, batchExportId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsBatchExportsRunsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/`
}

export const environmentsBatchExportsRunsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportRunApi> => {
    return apiMutator<BatchExportRunApi>(getEnvironmentsBatchExportsRunsRetrieveUrl(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Cancel a batch export run.
 */
export const getEnvironmentsBatchExportsRunsCancelCreateUrl = (
    projectId: string,
    batchExportId: string,
    id: string
) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/cancel/`
}

export const environmentsBatchExportsRunsCancelCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsRunsCancelCreateUrl(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportRunApi),
    })
}

export const getEnvironmentsBatchExportsRunsLogsRetrieveUrl = (
    projectId: string,
    batchExportId: string,
    id: string
) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/`
}

export const environmentsBatchExportsRunsLogsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsRunsLogsRetrieveUrl(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Retry a batch export run.

We use the same underlying mechanism as when backfilling a batch export, as retrying
a run is the same as backfilling one run.
 */
export const getEnvironmentsBatchExportsRunsRetryCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
}

export const environmentsBatchExportsRunsRetryCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsRunsRetryCreateUrl(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportRunApi),
    })
}

export const getEnvironmentsBatchExportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const environmentsBatchExportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getEnvironmentsBatchExportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsBatchExportsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const environmentsBatchExportsUpdate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getEnvironmentsBatchExportsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getEnvironmentsBatchExportsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const environmentsBatchExportsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getEnvironmentsBatchExportsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export const getEnvironmentsBatchExportsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const environmentsBatchExportsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a backfill for a BatchExport.

Note: This endpoint is deprecated. Please use POST /batch_exports/<id>/backfills/ instead.
 */
export const getEnvironmentsBatchExportsBackfillCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/backfill/`
}

export const environmentsBatchExportsBackfillCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsBackfillCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getEnvironmentsBatchExportsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/logs/`
}

export const environmentsBatchExportsLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export const getEnvironmentsBatchExportsPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/pause/`
}

export const environmentsBatchExportsPauseCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsPauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getEnvironmentsBatchExportsRunTestStepCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/run_test_step/`
}

export const environmentsBatchExportsRunTestStepCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsRunTestStepCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * Unpause a BatchExport.
 */
export const getEnvironmentsBatchExportsUnpauseCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/unpause/`
}

export const environmentsBatchExportsUnpauseCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsUnpauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getEnvironmentsBatchExportsRunTestStepNewCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/run_test_step_new/`
}

export const environmentsBatchExportsRunTestStepNewCreate = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsRunTestStepNewCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getEnvironmentsBatchExportsTestRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/test/`
}

export const environmentsBatchExportsTestRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEnvironmentsBatchExportsTestRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsListUrl = (organizationId: string, params?: BatchExportsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/batch_exports/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/batch_exports/`
}

export const batchExportsList = async (
    organizationId: string,
    params?: BatchExportsListParams,
    options?: RequestInit
): Promise<PaginatedBatchExportListApi> => {
    return apiMutator<PaginatedBatchExportListApi>(getBatchExportsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/`
}

export const batchExportsCreate = async (
    organizationId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsUpdate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export const getBatchExportsDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsDestroy = async (organizationId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a backfill for a BatchExport.

Note: This endpoint is deprecated. Please use POST /batch_exports/<id>/backfills/ instead.
 */
export const getBatchExportsBackfillCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/backfill/`
}

export const batchExportsBackfillCreate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsBackfillCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsLogsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsLogsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export const getBatchExportsPauseCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsPauseCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * Unpause a BatchExport.
 */
export const getBatchExportsUnpauseCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsUnpauseCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepNewCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate = async (
    organizationId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepNewCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsTestRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/test/`
}

export const batchExportsTestRetrieve = async (organizationId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsTestRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsList2Url = (projectId: string, params?: BatchExportsList2Params) => {
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

export const batchExportsList2 = async (
    projectId: string,
    params?: BatchExportsList2Params,
    options?: RequestInit
): Promise<PaginatedBatchExportListApi> => {
    return apiMutator<PaginatedBatchExportListApi>(getBatchExportsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/`
}

export const batchExportsCreate2 = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
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

/**
 * Create a new backfill for a BatchExport.
 */
export const getBatchExportsBackfillsCreateUrl = (projectId: string, batchExportId: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/`
}

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

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export const getBatchExportsBackfillsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/${id}/`
}

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

/**
 * Cancel a batch export backfill.
 */
export const getBatchExportsBackfillsCancelCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/${id}/cancel/`
}

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

/**
 * Cancel a batch export run.
 */
export const getBatchExportsRunsCancelCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/cancel/`
}

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

export const getBatchExportsRunsLogsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/`
}

export const batchExportsRunsLogsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunsLogsRetrieveUrl(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Retry a batch export run.

We use the same underlying mechanism as when backfilling a batch export, as retrying
a run is the same as backfilling one run.
 */
export const getBatchExportsRunsRetryCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
}

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

export const getBatchExportsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsUpdate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export const getBatchExportsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsDestroy2 = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a backfill for a BatchExport.

Note: This endpoint is deprecated. Please use POST /batch_exports/<id>/backfills/ instead.
 */
export const getBatchExportsBackfillCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/backfill/`
}

export const batchExportsBackfillCreate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsBackfillCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsLogsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsLogsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export const getBatchExportsPauseCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsPauseCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * Unpause a BatchExport.
 */
export const getBatchExportsUnpauseCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsUnpauseCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepNewCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate2 = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepNewCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsTestRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/test/`
}

export const batchExportsTestRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsTestRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}
