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
    BatchExportRunApi,
    BatchExportsList2Params,
    BatchExportsListParams,
    BatchExportsRunsListParams,
    EnvironmentsBatchExportsListParams,
    EnvironmentsBatchExportsRunsListParams,
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

export type environmentsBatchExportsListResponse200 = {
    data: PaginatedBatchExportListApi
    status: 200
}

export type environmentsBatchExportsListResponseSuccess = environmentsBatchExportsListResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsListResponse = environmentsBatchExportsListResponseSuccess

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
): Promise<environmentsBatchExportsListResponse> => {
    return apiMutator<environmentsBatchExportsListResponse>(getEnvironmentsBatchExportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsBatchExportsCreateResponse201 = {
    data: BatchExportApi
    status: 201
}

export type environmentsBatchExportsCreateResponseSuccess = environmentsBatchExportsCreateResponse201 & {
    headers: Headers
}
export type environmentsBatchExportsCreateResponse = environmentsBatchExportsCreateResponseSuccess

export const getEnvironmentsBatchExportsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/`
}

export const environmentsBatchExportsCreate = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsCreateResponse> => {
    return apiMutator<environmentsBatchExportsCreateResponse>(getEnvironmentsBatchExportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type environmentsBatchExportsRunsListResponse200 = {
    data: PaginatedBatchExportRunListApi
    status: 200
}

export type environmentsBatchExportsRunsListResponseSuccess = environmentsBatchExportsRunsListResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsRunsListResponse = environmentsBatchExportsRunsListResponseSuccess

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
): Promise<environmentsBatchExportsRunsListResponse> => {
    return apiMutator<environmentsBatchExportsRunsListResponse>(
        getEnvironmentsBatchExportsRunsListUrl(projectId, batchExportId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsBatchExportsRunsRetrieveResponse200 = {
    data: BatchExportRunApi
    status: 200
}

export type environmentsBatchExportsRunsRetrieveResponseSuccess = environmentsBatchExportsRunsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsRunsRetrieveResponse = environmentsBatchExportsRunsRetrieveResponseSuccess

export const getEnvironmentsBatchExportsRunsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/`
}

export const environmentsBatchExportsRunsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsBatchExportsRunsRetrieveResponse> => {
    return apiMutator<environmentsBatchExportsRunsRetrieveResponse>(
        getEnvironmentsBatchExportsRunsRetrieveUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Cancel a batch export run.
 */
export type environmentsBatchExportsRunsCancelCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsRunsCancelCreateResponseSuccess =
    environmentsBatchExportsRunsCancelCreateResponse200 & {
        headers: Headers
    }
export type environmentsBatchExportsRunsCancelCreateResponse = environmentsBatchExportsRunsCancelCreateResponseSuccess

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
): Promise<environmentsBatchExportsRunsCancelCreateResponse> => {
    return apiMutator<environmentsBatchExportsRunsCancelCreateResponse>(
        getEnvironmentsBatchExportsRunsCancelCreateUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportRunApi),
        }
    )
}

export type environmentsBatchExportsRunsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsRunsLogsRetrieveResponseSuccess =
    environmentsBatchExportsRunsLogsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsBatchExportsRunsLogsRetrieveResponse = environmentsBatchExportsRunsLogsRetrieveResponseSuccess

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
): Promise<environmentsBatchExportsRunsLogsRetrieveResponse> => {
    return apiMutator<environmentsBatchExportsRunsLogsRetrieveResponse>(
        getEnvironmentsBatchExportsRunsLogsRetrieveUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Retry a batch export run.

We use the same underlying mechanism as when backfilling a batch export, as retrying
a run is the same as backfilling one run.
 */
export type environmentsBatchExportsRunsRetryCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsRunsRetryCreateResponseSuccess =
    environmentsBatchExportsRunsRetryCreateResponse200 & {
        headers: Headers
    }
export type environmentsBatchExportsRunsRetryCreateResponse = environmentsBatchExportsRunsRetryCreateResponseSuccess

export const getEnvironmentsBatchExportsRunsRetryCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
}

export const environmentsBatchExportsRunsRetryCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsRunsRetryCreateResponse> => {
    return apiMutator<environmentsBatchExportsRunsRetryCreateResponse>(
        getEnvironmentsBatchExportsRunsRetryCreateUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportRunApi),
        }
    )
}

export type environmentsBatchExportsRetrieveResponse200 = {
    data: BatchExportApi
    status: 200
}

export type environmentsBatchExportsRetrieveResponseSuccess = environmentsBatchExportsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsRetrieveResponse = environmentsBatchExportsRetrieveResponseSuccess

export const getEnvironmentsBatchExportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const environmentsBatchExportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsBatchExportsRetrieveResponse> => {
    return apiMutator<environmentsBatchExportsRetrieveResponse>(getEnvironmentsBatchExportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsBatchExportsUpdateResponse200 = {
    data: BatchExportApi
    status: 200
}

export type environmentsBatchExportsUpdateResponseSuccess = environmentsBatchExportsUpdateResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsUpdateResponse = environmentsBatchExportsUpdateResponseSuccess

export const getEnvironmentsBatchExportsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const environmentsBatchExportsUpdate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsUpdateResponse> => {
    return apiMutator<environmentsBatchExportsUpdateResponse>(getEnvironmentsBatchExportsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type environmentsBatchExportsPartialUpdateResponse200 = {
    data: BatchExportApi
    status: 200
}

export type environmentsBatchExportsPartialUpdateResponseSuccess = environmentsBatchExportsPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsPartialUpdateResponse = environmentsBatchExportsPartialUpdateResponseSuccess

export const getEnvironmentsBatchExportsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const environmentsBatchExportsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsPartialUpdateResponse> => {
    return apiMutator<environmentsBatchExportsPartialUpdateResponse>(
        getEnvironmentsBatchExportsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedBatchExportApi),
        }
    )
}

export type environmentsBatchExportsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsBatchExportsDestroyResponseSuccess = environmentsBatchExportsDestroyResponse204 & {
    headers: Headers
}
export type environmentsBatchExportsDestroyResponse = environmentsBatchExportsDestroyResponseSuccess

export const getEnvironmentsBatchExportsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const environmentsBatchExportsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsBatchExportsDestroyResponse> => {
    return apiMutator<environmentsBatchExportsDestroyResponse>(getEnvironmentsBatchExportsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a backfill for a BatchExport.

Note: This endpoint is deprecated. Please use POST /batch_exports/<id>/backfills/ instead.
 */
export type environmentsBatchExportsBackfillCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsBackfillCreateResponseSuccess =
    environmentsBatchExportsBackfillCreateResponse200 & {
        headers: Headers
    }
export type environmentsBatchExportsBackfillCreateResponse = environmentsBatchExportsBackfillCreateResponseSuccess

export const getEnvironmentsBatchExportsBackfillCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/backfill/`
}

export const environmentsBatchExportsBackfillCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsBackfillCreateResponse> => {
    return apiMutator<environmentsBatchExportsBackfillCreateResponse>(
        getEnvironmentsBatchExportsBackfillCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportApi),
        }
    )
}

export type environmentsBatchExportsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsLogsRetrieveResponseSuccess = environmentsBatchExportsLogsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsLogsRetrieveResponse = environmentsBatchExportsLogsRetrieveResponseSuccess

export const getEnvironmentsBatchExportsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/logs/`
}

export const environmentsBatchExportsLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsBatchExportsLogsRetrieveResponse> => {
    return apiMutator<environmentsBatchExportsLogsRetrieveResponse>(
        getEnvironmentsBatchExportsLogsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Pause a BatchExport.
 */
export type environmentsBatchExportsPauseCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsPauseCreateResponseSuccess = environmentsBatchExportsPauseCreateResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsPauseCreateResponse = environmentsBatchExportsPauseCreateResponseSuccess

export const getEnvironmentsBatchExportsPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/pause/`
}

export const environmentsBatchExportsPauseCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsPauseCreateResponse> => {
    return apiMutator<environmentsBatchExportsPauseCreateResponse>(
        getEnvironmentsBatchExportsPauseCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportApi),
        }
    )
}

export type environmentsBatchExportsRunTestStepCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsRunTestStepCreateResponseSuccess =
    environmentsBatchExportsRunTestStepCreateResponse200 & {
        headers: Headers
    }
export type environmentsBatchExportsRunTestStepCreateResponse = environmentsBatchExportsRunTestStepCreateResponseSuccess

export const getEnvironmentsBatchExportsRunTestStepCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/run_test_step/`
}

export const environmentsBatchExportsRunTestStepCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsRunTestStepCreateResponse> => {
    return apiMutator<environmentsBatchExportsRunTestStepCreateResponse>(
        getEnvironmentsBatchExportsRunTestStepCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportApi),
        }
    )
}

/**
 * Unpause a BatchExport.
 */
export type environmentsBatchExportsUnpauseCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsUnpauseCreateResponseSuccess = environmentsBatchExportsUnpauseCreateResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsUnpauseCreateResponse = environmentsBatchExportsUnpauseCreateResponseSuccess

export const getEnvironmentsBatchExportsUnpauseCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/unpause/`
}

export const environmentsBatchExportsUnpauseCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsUnpauseCreateResponse> => {
    return apiMutator<environmentsBatchExportsUnpauseCreateResponse>(
        getEnvironmentsBatchExportsUnpauseCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportApi),
        }
    )
}

export type environmentsBatchExportsRunTestStepNewCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsRunTestStepNewCreateResponseSuccess =
    environmentsBatchExportsRunTestStepNewCreateResponse200 & {
        headers: Headers
    }
export type environmentsBatchExportsRunTestStepNewCreateResponse =
    environmentsBatchExportsRunTestStepNewCreateResponseSuccess

export const getEnvironmentsBatchExportsRunTestStepNewCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/run_test_step_new/`
}

export const environmentsBatchExportsRunTestStepNewCreate = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<environmentsBatchExportsRunTestStepNewCreateResponse> => {
    return apiMutator<environmentsBatchExportsRunTestStepNewCreateResponse>(
        getEnvironmentsBatchExportsRunTestStepNewCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportApi),
        }
    )
}

export type environmentsBatchExportsTestRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsBatchExportsTestRetrieveResponseSuccess = environmentsBatchExportsTestRetrieveResponse200 & {
    headers: Headers
}
export type environmentsBatchExportsTestRetrieveResponse = environmentsBatchExportsTestRetrieveResponseSuccess

export const getEnvironmentsBatchExportsTestRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/test/`
}

export const environmentsBatchExportsTestRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsBatchExportsTestRetrieveResponse> => {
    return apiMutator<environmentsBatchExportsTestRetrieveResponse>(
        getEnvironmentsBatchExportsTestRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type batchExportsListResponse200 = {
    data: PaginatedBatchExportListApi
    status: 200
}

export type batchExportsListResponseSuccess = batchExportsListResponse200 & {
    headers: Headers
}
export type batchExportsListResponse = batchExportsListResponseSuccess

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
): Promise<batchExportsListResponse> => {
    return apiMutator<batchExportsListResponse>(getBatchExportsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsCreateResponse201 = {
    data: BatchExportApi
    status: 201
}

export type batchExportsCreateResponseSuccess = batchExportsCreateResponse201 & {
    headers: Headers
}
export type batchExportsCreateResponse = batchExportsCreateResponseSuccess

export const getBatchExportsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/`
}

export const batchExportsCreate = async (
    organizationId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsCreateResponse> => {
    return apiMutator<batchExportsCreateResponse>(getBatchExportsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRetrieveResponse200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsRetrieveResponseSuccess = batchExportsRetrieveResponse200 & {
    headers: Headers
}
export type batchExportsRetrieveResponse = batchExportsRetrieveResponseSuccess

export const getBatchExportsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRetrieveResponse> => {
    return apiMutator<batchExportsRetrieveResponse>(getBatchExportsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsUpdateResponse200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsUpdateResponseSuccess = batchExportsUpdateResponse200 & {
    headers: Headers
}
export type batchExportsUpdateResponse = batchExportsUpdateResponseSuccess

export const getBatchExportsUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsUpdate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUpdateResponse> => {
    return apiMutator<batchExportsUpdateResponse>(getBatchExportsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsPartialUpdateResponse200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsPartialUpdateResponseSuccess = batchExportsPartialUpdateResponse200 & {
    headers: Headers
}
export type batchExportsPartialUpdateResponse = batchExportsPartialUpdateResponseSuccess

export const getBatchExportsPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPartialUpdateResponse> => {
    return apiMutator<batchExportsPartialUpdateResponse>(getBatchExportsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export type batchExportsDestroyResponse204 = {
    data: void
    status: 204
}

export type batchExportsDestroyResponseSuccess = batchExportsDestroyResponse204 & {
    headers: Headers
}
export type batchExportsDestroyResponse = batchExportsDestroyResponseSuccess

export const getBatchExportsDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsDestroyResponse> => {
    return apiMutator<batchExportsDestroyResponse>(getBatchExportsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a backfill for a BatchExport.

Note: This endpoint is deprecated. Please use POST /batch_exports/<id>/backfills/ instead.
 */
export type batchExportsBackfillCreateResponse200 = {
    data: void
    status: 200
}

export type batchExportsBackfillCreateResponseSuccess = batchExportsBackfillCreateResponse200 & {
    headers: Headers
}
export type batchExportsBackfillCreateResponse = batchExportsBackfillCreateResponseSuccess

export const getBatchExportsBackfillCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/backfill/`
}

export const batchExportsBackfillCreate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsBackfillCreateResponse> => {
    return apiMutator<batchExportsBackfillCreateResponse>(getBatchExportsBackfillCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type batchExportsLogsRetrieveResponseSuccess = batchExportsLogsRetrieveResponse200 & {
    headers: Headers
}
export type batchExportsLogsRetrieveResponse = batchExportsLogsRetrieveResponseSuccess

export const getBatchExportsLogsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsLogsRetrieveResponse> => {
    return apiMutator<batchExportsLogsRetrieveResponse>(getBatchExportsLogsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export type batchExportsPauseCreateResponse200 = {
    data: void
    status: 200
}

export type batchExportsPauseCreateResponseSuccess = batchExportsPauseCreateResponse200 & {
    headers: Headers
}
export type batchExportsPauseCreateResponse = batchExportsPauseCreateResponseSuccess

export const getBatchExportsPauseCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPauseCreateResponse> => {
    return apiMutator<batchExportsPauseCreateResponse>(getBatchExportsPauseCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRunTestStepCreateResponse200 = {
    data: void
    status: 200
}

export type batchExportsRunTestStepCreateResponseSuccess = batchExportsRunTestStepCreateResponse200 & {
    headers: Headers
}
export type batchExportsRunTestStepCreateResponse = batchExportsRunTestStepCreateResponseSuccess

export const getBatchExportsRunTestStepCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepCreateResponse> => {
    return apiMutator<batchExportsRunTestStepCreateResponse>(getBatchExportsRunTestStepCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * Unpause a BatchExport.
 */
export type batchExportsUnpauseCreateResponse200 = {
    data: void
    status: 200
}

export type batchExportsUnpauseCreateResponseSuccess = batchExportsUnpauseCreateResponse200 & {
    headers: Headers
}
export type batchExportsUnpauseCreateResponse = batchExportsUnpauseCreateResponseSuccess

export const getBatchExportsUnpauseCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUnpauseCreateResponse> => {
    return apiMutator<batchExportsUnpauseCreateResponse>(getBatchExportsUnpauseCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRunTestStepNewCreateResponse200 = {
    data: void
    status: 200
}

export type batchExportsRunTestStepNewCreateResponseSuccess = batchExportsRunTestStepNewCreateResponse200 & {
    headers: Headers
}
export type batchExportsRunTestStepNewCreateResponse = batchExportsRunTestStepNewCreateResponseSuccess

export const getBatchExportsRunTestStepNewCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate = async (
    organizationId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepNewCreateResponse> => {
    return apiMutator<batchExportsRunTestStepNewCreateResponse>(
        getBatchExportsRunTestStepNewCreateUrl(organizationId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportApi),
        }
    )
}

export type batchExportsTestRetrieveResponse200 = {
    data: void
    status: 200
}

export type batchExportsTestRetrieveResponseSuccess = batchExportsTestRetrieveResponse200 & {
    headers: Headers
}
export type batchExportsTestRetrieveResponse = batchExportsTestRetrieveResponseSuccess

export const getBatchExportsTestRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/test/`
}

export const batchExportsTestRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<batchExportsTestRetrieveResponse> => {
    return apiMutator<batchExportsTestRetrieveResponse>(getBatchExportsTestRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsList2Response200 = {
    data: PaginatedBatchExportListApi
    status: 200
}

export type batchExportsList2ResponseSuccess = batchExportsList2Response200 & {
    headers: Headers
}
export type batchExportsList2Response = batchExportsList2ResponseSuccess

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
): Promise<batchExportsList2Response> => {
    return apiMutator<batchExportsList2Response>(getBatchExportsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsCreate2Response201 = {
    data: BatchExportApi
    status: 201
}

export type batchExportsCreate2ResponseSuccess = batchExportsCreate2Response201 & {
    headers: Headers
}
export type batchExportsCreate2Response = batchExportsCreate2ResponseSuccess

export const getBatchExportsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/`
}

export const batchExportsCreate2 = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsCreate2Response> => {
    return apiMutator<batchExportsCreate2Response>(getBatchExportsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRunsListResponse200 = {
    data: PaginatedBatchExportRunListApi
    status: 200
}

export type batchExportsRunsListResponseSuccess = batchExportsRunsListResponse200 & {
    headers: Headers
}
export type batchExportsRunsListResponse = batchExportsRunsListResponseSuccess

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
): Promise<batchExportsRunsListResponse> => {
    return apiMutator<batchExportsRunsListResponse>(getBatchExportsRunsListUrl(projectId, batchExportId, params), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsRunsRetrieveResponse200 = {
    data: BatchExportRunApi
    status: 200
}

export type batchExportsRunsRetrieveResponseSuccess = batchExportsRunsRetrieveResponse200 & {
    headers: Headers
}
export type batchExportsRunsRetrieveResponse = batchExportsRunsRetrieveResponseSuccess

export const getBatchExportsRunsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/`
}

export const batchExportsRunsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRunsRetrieveResponse> => {
    return apiMutator<batchExportsRunsRetrieveResponse>(getBatchExportsRunsRetrieveUrl(projectId, batchExportId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Cancel a batch export run.
 */
export type batchExportsRunsCancelCreateResponse200 = {
    data: void
    status: 200
}

export type batchExportsRunsCancelCreateResponseSuccess = batchExportsRunsCancelCreateResponse200 & {
    headers: Headers
}
export type batchExportsRunsCancelCreateResponse = batchExportsRunsCancelCreateResponseSuccess

export const getBatchExportsRunsCancelCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/cancel/`
}

export const batchExportsRunsCancelCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<batchExportsRunsCancelCreateResponse> => {
    return apiMutator<batchExportsRunsCancelCreateResponse>(
        getBatchExportsRunsCancelCreateUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportRunApi),
        }
    )
}

export type batchExportsRunsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type batchExportsRunsLogsRetrieveResponseSuccess = batchExportsRunsLogsRetrieveResponse200 & {
    headers: Headers
}
export type batchExportsRunsLogsRetrieveResponse = batchExportsRunsLogsRetrieveResponseSuccess

export const getBatchExportsRunsLogsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/`
}

export const batchExportsRunsLogsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRunsLogsRetrieveResponse> => {
    return apiMutator<batchExportsRunsLogsRetrieveResponse>(
        getBatchExportsRunsLogsRetrieveUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Retry a batch export run.

We use the same underlying mechanism as when backfilling a batch export, as retrying
a run is the same as backfilling one run.
 */
export type batchExportsRunsRetryCreateResponse200 = {
    data: void
    status: 200
}

export type batchExportsRunsRetryCreateResponseSuccess = batchExportsRunsRetryCreateResponse200 & {
    headers: Headers
}
export type batchExportsRunsRetryCreateResponse = batchExportsRunsRetryCreateResponseSuccess

export const getBatchExportsRunsRetryCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
}

export const batchExportsRunsRetryCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<batchExportsRunsRetryCreateResponse> => {
    return apiMutator<batchExportsRunsRetryCreateResponse>(
        getBatchExportsRunsRetryCreateUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportRunApi),
        }
    )
}

export type batchExportsRetrieve2Response200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsRetrieve2ResponseSuccess = batchExportsRetrieve2Response200 & {
    headers: Headers
}
export type batchExportsRetrieve2Response = batchExportsRetrieve2ResponseSuccess

export const getBatchExportsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRetrieve2Response> => {
    return apiMutator<batchExportsRetrieve2Response>(getBatchExportsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsUpdate2Response200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsUpdate2ResponseSuccess = batchExportsUpdate2Response200 & {
    headers: Headers
}
export type batchExportsUpdate2Response = batchExportsUpdate2ResponseSuccess

export const getBatchExportsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsUpdate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUpdate2Response> => {
    return apiMutator<batchExportsUpdate2Response>(getBatchExportsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsPartialUpdate2Response200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsPartialUpdate2ResponseSuccess = batchExportsPartialUpdate2Response200 & {
    headers: Headers
}
export type batchExportsPartialUpdate2Response = batchExportsPartialUpdate2ResponseSuccess

export const getBatchExportsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPartialUpdate2Response> => {
    return apiMutator<batchExportsPartialUpdate2Response>(getBatchExportsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export type batchExportsDestroy2Response204 = {
    data: void
    status: 204
}

export type batchExportsDestroy2ResponseSuccess = batchExportsDestroy2Response204 & {
    headers: Headers
}
export type batchExportsDestroy2Response = batchExportsDestroy2ResponseSuccess

export const getBatchExportsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsDestroy2Response> => {
    return apiMutator<batchExportsDestroy2Response>(getBatchExportsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a backfill for a BatchExport.

Note: This endpoint is deprecated. Please use POST /batch_exports/<id>/backfills/ instead.
 */
export type batchExportsBackfillCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsBackfillCreate2ResponseSuccess = batchExportsBackfillCreate2Response200 & {
    headers: Headers
}
export type batchExportsBackfillCreate2Response = batchExportsBackfillCreate2ResponseSuccess

export const getBatchExportsBackfillCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/backfill/`
}

export const batchExportsBackfillCreate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsBackfillCreate2Response> => {
    return apiMutator<batchExportsBackfillCreate2Response>(getBatchExportsBackfillCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsLogsRetrieve2Response200 = {
    data: void
    status: 200
}

export type batchExportsLogsRetrieve2ResponseSuccess = batchExportsLogsRetrieve2Response200 & {
    headers: Headers
}
export type batchExportsLogsRetrieve2Response = batchExportsLogsRetrieve2ResponseSuccess

export const getBatchExportsLogsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsLogsRetrieve2Response> => {
    return apiMutator<batchExportsLogsRetrieve2Response>(getBatchExportsLogsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export type batchExportsPauseCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsPauseCreate2ResponseSuccess = batchExportsPauseCreate2Response200 & {
    headers: Headers
}
export type batchExportsPauseCreate2Response = batchExportsPauseCreate2ResponseSuccess

export const getBatchExportsPauseCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPauseCreate2Response> => {
    return apiMutator<batchExportsPauseCreate2Response>(getBatchExportsPauseCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRunTestStepCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsRunTestStepCreate2ResponseSuccess = batchExportsRunTestStepCreate2Response200 & {
    headers: Headers
}
export type batchExportsRunTestStepCreate2Response = batchExportsRunTestStepCreate2ResponseSuccess

export const getBatchExportsRunTestStepCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepCreate2Response> => {
    return apiMutator<batchExportsRunTestStepCreate2Response>(getBatchExportsRunTestStepCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * Unpause a BatchExport.
 */
export type batchExportsUnpauseCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsUnpauseCreate2ResponseSuccess = batchExportsUnpauseCreate2Response200 & {
    headers: Headers
}
export type batchExportsUnpauseCreate2Response = batchExportsUnpauseCreate2ResponseSuccess

export const getBatchExportsUnpauseCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate2 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUnpauseCreate2Response> => {
    return apiMutator<batchExportsUnpauseCreate2Response>(getBatchExportsUnpauseCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRunTestStepNewCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsRunTestStepNewCreate2ResponseSuccess = batchExportsRunTestStepNewCreate2Response200 & {
    headers: Headers
}
export type batchExportsRunTestStepNewCreate2Response = batchExportsRunTestStepNewCreate2ResponseSuccess

export const getBatchExportsRunTestStepNewCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate2 = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepNewCreate2Response> => {
    return apiMutator<batchExportsRunTestStepNewCreate2Response>(getBatchExportsRunTestStepNewCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsTestRetrieve2Response200 = {
    data: void
    status: 200
}

export type batchExportsTestRetrieve2ResponseSuccess = batchExportsTestRetrieve2Response200 & {
    headers: Headers
}
export type batchExportsTestRetrieve2Response = batchExportsTestRetrieve2ResponseSuccess

export const getBatchExportsTestRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/test/`
}

export const batchExportsTestRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<batchExportsTestRetrieve2Response> => {
    return apiMutator<batchExportsTestRetrieve2Response>(getBatchExportsTestRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}
