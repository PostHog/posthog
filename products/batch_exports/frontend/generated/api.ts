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
    BatchExportsBackfillsList2Params,
    BatchExportsBackfillsListParams,
    BatchExportsList2Params,
    BatchExportsList3Params,
    BatchExportsListParams,
    BatchExportsRunsList2Params,
    BatchExportsRunsListParams,
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

export const getBatchExportsListUrl = (projectId: string, params?: BatchExportsListParams) => {
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
    return `/api/environments/${projectId}/batch_exports/`
}

export const batchExportsCreate = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsCreateUrl(projectId), {
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
        ? `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/?${stringifiedParams}`
        : `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/${id}/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/${id}/cancel/`
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
        ? `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/?${stringifiedParams}`
        : `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/cancel/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
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

export const getBatchExportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
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
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const batchExportsUpdate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export const getBatchExportsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const batchExportsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getBatchExportsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export const getBatchExportsPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/pause/`
}

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
    return `/api/environments/${projectId}/batch_exports/${id}/run_test_step/`
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

/**
 * Unpause a BatchExport.
 */
export const getBatchExportsUnpauseCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/unpause/`
}

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
    return `/api/environments/${projectId}/batch_exports/run_test_step_new/`
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
    return `/api/environments/${projectId}/batch_exports/test/`
}

export const batchExportsTestRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsTestRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsList2Url = (organizationId: string, params?: BatchExportsList2Params) => {
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

export const batchExportsList2 = async (
    organizationId: string,
    params?: BatchExportsList2Params,
    options?: RequestInit
): Promise<PaginatedBatchExportListApi> => {
    return apiMutator<PaginatedBatchExportListApi>(getBatchExportsList2Url(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsCreate2Url = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/`
}

export const batchExportsCreate2 = async (
    organizationId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsCreate2Url(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRetrieve2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsRetrieve2 = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsRetrieve2Url(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsUpdate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsUpdate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsUpdate2Url(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsPartialUpdate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate2 = async (
    organizationId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsPartialUpdate2Url(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export const getBatchExportsDestroy2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsDestroy2 = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsDestroy2Url(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getBatchExportsLogsRetrieve2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve2 = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsLogsRetrieve2Url(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export const getBatchExportsPauseCreate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsPauseCreate2Url(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepCreate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepCreate2Url(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * Unpause a BatchExport.
 */
export const getBatchExportsUnpauseCreate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsUnpauseCreate2Url(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepNewCreate2Url = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate2 = async (
    organizationId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepNewCreate2Url(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsTestRetrieve2Url = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/test/`
}

export const batchExportsTestRetrieve2 = async (organizationId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsTestRetrieve2Url(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsList3Url = (projectId: string, params?: BatchExportsList3Params) => {
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

export const batchExportsList3 = async (
    projectId: string,
    params?: BatchExportsList3Params,
    options?: RequestInit
): Promise<PaginatedBatchExportListApi> => {
    return apiMutator<PaginatedBatchExportListApi>(getBatchExportsList3Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsCreate3Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/`
}

export const batchExportsCreate3 = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsCreate3Url(projectId), {
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
export const getBatchExportsBackfillsList2Url = (
    projectId: string,
    batchExportId: string,
    params?: BatchExportsBackfillsList2Params
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

export const batchExportsBackfillsList2 = async (
    projectId: string,
    batchExportId: string,
    params?: BatchExportsBackfillsList2Params,
    options?: RequestInit
): Promise<PaginatedBatchExportBackfillListApi> => {
    return apiMutator<PaginatedBatchExportBackfillListApi>(
        getBatchExportsBackfillsList2Url(projectId, batchExportId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create a new backfill for a BatchExport.
 */
export const getBatchExportsBackfillsCreate2Url = (projectId: string, batchExportId: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/`
}

export const batchExportsBackfillsCreate2 = async (
    projectId: string,
    batchExportId: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<BatchExportBackfillApi> => {
    return apiMutator<BatchExportBackfillApi>(getBatchExportsBackfillsCreate2Url(projectId, batchExportId), {
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
export const getBatchExportsBackfillsRetrieve2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/${id}/`
}

export const batchExportsBackfillsRetrieve2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportBackfillApi> => {
    return apiMutator<BatchExportBackfillApi>(getBatchExportsBackfillsRetrieve2Url(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Cancel a batch export backfill.
 */
export const getBatchExportsBackfillsCancelCreate2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/${id}/cancel/`
}

export const batchExportsBackfillsCancelCreate2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsBackfillsCancelCreate2Url(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportBackfillApi),
    })
}

export const getBatchExportsRunsList2Url = (
    projectId: string,
    batchExportId: string,
    params?: BatchExportsRunsList2Params
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

export const batchExportsRunsList2 = async (
    projectId: string,
    batchExportId: string,
    params?: BatchExportsRunsList2Params,
    options?: RequestInit
): Promise<PaginatedBatchExportRunListApi> => {
    return apiMutator<PaginatedBatchExportRunListApi>(getBatchExportsRunsList2Url(projectId, batchExportId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsRunsRetrieve2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/`
}

export const batchExportsRunsRetrieve2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportRunApi> => {
    return apiMutator<BatchExportRunApi>(getBatchExportsRunsRetrieve2Url(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Cancel a batch export run.
 */
export const getBatchExportsRunsCancelCreate2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/cancel/`
}

export const batchExportsRunsCancelCreate2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunsCancelCreate2Url(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportRunApi),
    })
}

export const getBatchExportsRunsLogsRetrieve2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/`
}

export const batchExportsRunsLogsRetrieve2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunsLogsRetrieve2Url(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Retry a batch export run.

We use the same underlying mechanism as when backfilling a batch export, as retrying
a run is the same as backfilling one run.
 */
export const getBatchExportsRunsRetryCreate2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
}

export const batchExportsRunsRetryCreate2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunsRetryCreate2Url(projectId, batchExportId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportRunApi),
    })
}

export const getBatchExportsRetrieve3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsRetrieve3 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsRetrieve3Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBatchExportsUpdate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsUpdate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsUpdate3Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsPartialUpdate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate3 = async (
    projectId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<BatchExportApi> => {
    return apiMutator<BatchExportApi>(getBatchExportsPartialUpdate3Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export const getBatchExportsDestroy3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsDestroy3 = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsDestroy3Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getBatchExportsLogsRetrieve3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve3 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsLogsRetrieve3Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export const getBatchExportsPauseCreate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsPauseCreate3Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepCreate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepCreate3Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * Unpause a BatchExport.
 */
export const getBatchExportsUnpauseCreate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsUnpauseCreate3Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsRunTestStepNewCreate3Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate3 = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBatchExportsRunTestStepNewCreate3Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export const getBatchExportsTestRetrieve3Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/test/`
}

export const batchExportsTestRetrieve3 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBatchExportsTestRetrieve3Url(projectId), {
        ...options,
        method: 'GET',
    })
}
