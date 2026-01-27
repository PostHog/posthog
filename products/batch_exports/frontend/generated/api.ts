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

export type batchExportsListResponse200 = {
    data: PaginatedBatchExportListApi
    status: 200
}

export type batchExportsListResponseSuccess = batchExportsListResponse200 & {
    headers: Headers
}
export type batchExportsListResponse = batchExportsListResponseSuccess

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
): Promise<batchExportsListResponse> => {
    return apiMutator<batchExportsListResponse>(getBatchExportsListUrl(projectId, params), {
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

export const getBatchExportsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/`
}

export const batchExportsCreate = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsCreateResponse> => {
    return apiMutator<batchExportsCreateResponse>(getBatchExportsCreateUrl(projectId), {
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
export type batchExportsBackfillsListResponse200 = {
    data: PaginatedBatchExportBackfillListApi
    status: 200
}

export type batchExportsBackfillsListResponseSuccess = batchExportsBackfillsListResponse200 & {
    headers: Headers
}
export type batchExportsBackfillsListResponse = batchExportsBackfillsListResponseSuccess

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
): Promise<batchExportsBackfillsListResponse> => {
    return apiMutator<batchExportsBackfillsListResponse>(
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
export type batchExportsBackfillsCreateResponse201 = {
    data: BatchExportBackfillApi
    status: 201
}

export type batchExportsBackfillsCreateResponseSuccess = batchExportsBackfillsCreateResponse201 & {
    headers: Headers
}
export type batchExportsBackfillsCreateResponse = batchExportsBackfillsCreateResponseSuccess

export const getBatchExportsBackfillsCreateUrl = (projectId: string, batchExportId: string) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/`
}

export const batchExportsBackfillsCreate = async (
    projectId: string,
    batchExportId: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<batchExportsBackfillsCreateResponse> => {
    return apiMutator<batchExportsBackfillsCreateResponse>(
        getBatchExportsBackfillsCreateUrl(projectId, batchExportId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportBackfillApi),
        }
    )
}

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export type batchExportsBackfillsRetrieveResponse200 = {
    data: BatchExportBackfillApi
    status: 200
}

export type batchExportsBackfillsRetrieveResponseSuccess = batchExportsBackfillsRetrieveResponse200 & {
    headers: Headers
}
export type batchExportsBackfillsRetrieveResponse = batchExportsBackfillsRetrieveResponseSuccess

export const getBatchExportsBackfillsRetrieveUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/${id}/`
}

export const batchExportsBackfillsRetrieve = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsBackfillsRetrieveResponse> => {
    return apiMutator<batchExportsBackfillsRetrieveResponse>(
        getBatchExportsBackfillsRetrieveUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Cancel a batch export backfill.
 */
export type batchExportsBackfillsCancelCreateResponse200 = {
    data: void
    status: 200
}

export type batchExportsBackfillsCancelCreateResponseSuccess = batchExportsBackfillsCancelCreateResponse200 & {
    headers: Headers
}
export type batchExportsBackfillsCancelCreateResponse = batchExportsBackfillsCancelCreateResponseSuccess

export const getBatchExportsBackfillsCancelCreateUrl = (projectId: string, batchExportId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/backfills/${id}/cancel/`
}

export const batchExportsBackfillsCancelCreate = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<batchExportsBackfillsCancelCreateResponse> => {
    return apiMutator<batchExportsBackfillsCancelCreateResponse>(
        getBatchExportsBackfillsCancelCreateUrl(projectId, batchExportId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportBackfillApi),
        }
    )
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
        ? `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/?${stringifiedParams}`
        : `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/cancel/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/`
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
    return `/api/environments/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
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

export type batchExportsRetrieveResponse200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsRetrieveResponseSuccess = batchExportsRetrieveResponse200 & {
    headers: Headers
}
export type batchExportsRetrieveResponse = batchExportsRetrieveResponseSuccess

export const getBatchExportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const batchExportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRetrieveResponse> => {
    return apiMutator<batchExportsRetrieveResponse>(getBatchExportsRetrieveUrl(projectId, id), {
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

export const getBatchExportsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const batchExportsUpdate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUpdateResponse> => {
    return apiMutator<batchExportsUpdateResponse>(getBatchExportsUpdateUrl(projectId, id), {
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

export const getBatchExportsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPartialUpdateResponse> => {
    return apiMutator<batchExportsPartialUpdateResponse>(getBatchExportsPartialUpdateUrl(projectId, id), {
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

export const getBatchExportsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/`
}

export const batchExportsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsDestroyResponse> => {
    return apiMutator<batchExportsDestroyResponse>(getBatchExportsDestroyUrl(projectId, id), {
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

export const getBatchExportsBackfillCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/backfill/`
}

export const batchExportsBackfillCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsBackfillCreateResponse> => {
    return apiMutator<batchExportsBackfillCreateResponse>(getBatchExportsBackfillCreateUrl(projectId, id), {
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

export const getBatchExportsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsLogsRetrieveResponse> => {
    return apiMutator<batchExportsLogsRetrieveResponse>(getBatchExportsLogsRetrieveUrl(projectId, id), {
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

export const getBatchExportsPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPauseCreateResponse> => {
    return apiMutator<batchExportsPauseCreateResponse>(getBatchExportsPauseCreateUrl(projectId, id), {
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

export const getBatchExportsRunTestStepCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepCreateResponse> => {
    return apiMutator<batchExportsRunTestStepCreateResponse>(getBatchExportsRunTestStepCreateUrl(projectId, id), {
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

export const getBatchExportsUnpauseCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUnpauseCreateResponse> => {
    return apiMutator<batchExportsUnpauseCreateResponse>(getBatchExportsUnpauseCreateUrl(projectId, id), {
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

export const getBatchExportsRunTestStepNewCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepNewCreateResponse> => {
    return apiMutator<batchExportsRunTestStepNewCreateResponse>(getBatchExportsRunTestStepNewCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsTestRetrieveResponse200 = {
    data: void
    status: 200
}

export type batchExportsTestRetrieveResponseSuccess = batchExportsTestRetrieveResponse200 & {
    headers: Headers
}
export type batchExportsTestRetrieveResponse = batchExportsTestRetrieveResponseSuccess

export const getBatchExportsTestRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/batch_exports/test/`
}

export const batchExportsTestRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<batchExportsTestRetrieveResponse> => {
    return apiMutator<batchExportsTestRetrieveResponse>(getBatchExportsTestRetrieveUrl(projectId), {
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
): Promise<batchExportsList2Response> => {
    return apiMutator<batchExportsList2Response>(getBatchExportsList2Url(organizationId, params), {
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

export const getBatchExportsCreate2Url = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/`
}

export const batchExportsCreate2 = async (
    organizationId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsCreate2Response> => {
    return apiMutator<batchExportsCreate2Response>(getBatchExportsCreate2Url(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRetrieve2Response200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsRetrieve2ResponseSuccess = batchExportsRetrieve2Response200 & {
    headers: Headers
}
export type batchExportsRetrieve2Response = batchExportsRetrieve2ResponseSuccess

export const getBatchExportsRetrieve2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsRetrieve2 = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRetrieve2Response> => {
    return apiMutator<batchExportsRetrieve2Response>(getBatchExportsRetrieve2Url(organizationId, id), {
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

export const getBatchExportsUpdate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsUpdate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUpdate2Response> => {
    return apiMutator<batchExportsUpdate2Response>(getBatchExportsUpdate2Url(organizationId, id), {
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

export const getBatchExportsPartialUpdate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate2 = async (
    organizationId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPartialUpdate2Response> => {
    return apiMutator<batchExportsPartialUpdate2Response>(getBatchExportsPartialUpdate2Url(organizationId, id), {
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

export const getBatchExportsDestroy2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/`
}

export const batchExportsDestroy2 = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsDestroy2Response> => {
    return apiMutator<batchExportsDestroy2Response>(getBatchExportsDestroy2Url(organizationId, id), {
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

export const getBatchExportsBackfillCreate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/backfill/`
}

export const batchExportsBackfillCreate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsBackfillCreate2Response> => {
    return apiMutator<batchExportsBackfillCreate2Response>(getBatchExportsBackfillCreate2Url(organizationId, id), {
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

export const getBatchExportsLogsRetrieve2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve2 = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsLogsRetrieve2Response> => {
    return apiMutator<batchExportsLogsRetrieve2Response>(getBatchExportsLogsRetrieve2Url(organizationId, id), {
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

export const getBatchExportsPauseCreate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPauseCreate2Response> => {
    return apiMutator<batchExportsPauseCreate2Response>(getBatchExportsPauseCreate2Url(organizationId, id), {
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

export const getBatchExportsRunTestStepCreate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepCreate2Response> => {
    return apiMutator<batchExportsRunTestStepCreate2Response>(
        getBatchExportsRunTestStepCreate2Url(organizationId, id),
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
export type batchExportsUnpauseCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsUnpauseCreate2ResponseSuccess = batchExportsUnpauseCreate2Response200 & {
    headers: Headers
}
export type batchExportsUnpauseCreate2Response = batchExportsUnpauseCreate2ResponseSuccess

export const getBatchExportsUnpauseCreate2Url = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate2 = async (
    organizationId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUnpauseCreate2Response> => {
    return apiMutator<batchExportsUnpauseCreate2Response>(getBatchExportsUnpauseCreate2Url(organizationId, id), {
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

export const getBatchExportsRunTestStepNewCreate2Url = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate2 = async (
    organizationId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepNewCreate2Response> => {
    return apiMutator<batchExportsRunTestStepNewCreate2Response>(
        getBatchExportsRunTestStepNewCreate2Url(organizationId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportApi),
        }
    )
}

export type batchExportsTestRetrieve2Response200 = {
    data: void
    status: 200
}

export type batchExportsTestRetrieve2ResponseSuccess = batchExportsTestRetrieve2Response200 & {
    headers: Headers
}
export type batchExportsTestRetrieve2Response = batchExportsTestRetrieve2ResponseSuccess

export const getBatchExportsTestRetrieve2Url = (organizationId: string) => {
    return `/api/organizations/${organizationId}/batch_exports/test/`
}

export const batchExportsTestRetrieve2 = async (
    organizationId: string,
    options?: RequestInit
): Promise<batchExportsTestRetrieve2Response> => {
    return apiMutator<batchExportsTestRetrieve2Response>(getBatchExportsTestRetrieve2Url(organizationId), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsList3Response200 = {
    data: PaginatedBatchExportListApi
    status: 200
}

export type batchExportsList3ResponseSuccess = batchExportsList3Response200 & {
    headers: Headers
}
export type batchExportsList3Response = batchExportsList3ResponseSuccess

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
): Promise<batchExportsList3Response> => {
    return apiMutator<batchExportsList3Response>(getBatchExportsList3Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsCreate3Response201 = {
    data: BatchExportApi
    status: 201
}

export type batchExportsCreate3ResponseSuccess = batchExportsCreate3Response201 & {
    headers: Headers
}
export type batchExportsCreate3Response = batchExportsCreate3ResponseSuccess

export const getBatchExportsCreate3Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/`
}

export const batchExportsCreate3 = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsCreate3Response> => {
    return apiMutator<batchExportsCreate3Response>(getBatchExportsCreate3Url(projectId), {
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
export type batchExportsBackfillsList2Response200 = {
    data: PaginatedBatchExportBackfillListApi
    status: 200
}

export type batchExportsBackfillsList2ResponseSuccess = batchExportsBackfillsList2Response200 & {
    headers: Headers
}
export type batchExportsBackfillsList2Response = batchExportsBackfillsList2ResponseSuccess

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
): Promise<batchExportsBackfillsList2Response> => {
    return apiMutator<batchExportsBackfillsList2Response>(
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
export type batchExportsBackfillsCreate2Response201 = {
    data: BatchExportBackfillApi
    status: 201
}

export type batchExportsBackfillsCreate2ResponseSuccess = batchExportsBackfillsCreate2Response201 & {
    headers: Headers
}
export type batchExportsBackfillsCreate2Response = batchExportsBackfillsCreate2ResponseSuccess

export const getBatchExportsBackfillsCreate2Url = (projectId: string, batchExportId: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/`
}

export const batchExportsBackfillsCreate2 = async (
    projectId: string,
    batchExportId: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<batchExportsBackfillsCreate2Response> => {
    return apiMutator<batchExportsBackfillsCreate2Response>(
        getBatchExportsBackfillsCreate2Url(projectId, batchExportId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportBackfillApi),
        }
    )
}

/**
 * ViewSet for BatchExportBackfill models.

Allows creating and reading backfills, but not updating or deleting them.
 */
export type batchExportsBackfillsRetrieve2Response200 = {
    data: BatchExportBackfillApi
    status: 200
}

export type batchExportsBackfillsRetrieve2ResponseSuccess = batchExportsBackfillsRetrieve2Response200 & {
    headers: Headers
}
export type batchExportsBackfillsRetrieve2Response = batchExportsBackfillsRetrieve2ResponseSuccess

export const getBatchExportsBackfillsRetrieve2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/${id}/`
}

export const batchExportsBackfillsRetrieve2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsBackfillsRetrieve2Response> => {
    return apiMutator<batchExportsBackfillsRetrieve2Response>(
        getBatchExportsBackfillsRetrieve2Url(projectId, batchExportId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Cancel a batch export backfill.
 */
export type batchExportsBackfillsCancelCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsBackfillsCancelCreate2ResponseSuccess = batchExportsBackfillsCancelCreate2Response200 & {
    headers: Headers
}
export type batchExportsBackfillsCancelCreate2Response = batchExportsBackfillsCancelCreate2ResponseSuccess

export const getBatchExportsBackfillsCancelCreate2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/backfills/${id}/cancel/`
}

export const batchExportsBackfillsCancelCreate2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportBackfillApi: NonReadonly<BatchExportBackfillApi>,
    options?: RequestInit
): Promise<batchExportsBackfillsCancelCreate2Response> => {
    return apiMutator<batchExportsBackfillsCancelCreate2Response>(
        getBatchExportsBackfillsCancelCreate2Url(projectId, batchExportId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportBackfillApi),
        }
    )
}

export type batchExportsRunsList2Response200 = {
    data: PaginatedBatchExportRunListApi
    status: 200
}

export type batchExportsRunsList2ResponseSuccess = batchExportsRunsList2Response200 & {
    headers: Headers
}
export type batchExportsRunsList2Response = batchExportsRunsList2ResponseSuccess

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
): Promise<batchExportsRunsList2Response> => {
    return apiMutator<batchExportsRunsList2Response>(getBatchExportsRunsList2Url(projectId, batchExportId, params), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsRunsRetrieve2Response200 = {
    data: BatchExportRunApi
    status: 200
}

export type batchExportsRunsRetrieve2ResponseSuccess = batchExportsRunsRetrieve2Response200 & {
    headers: Headers
}
export type batchExportsRunsRetrieve2Response = batchExportsRunsRetrieve2ResponseSuccess

export const getBatchExportsRunsRetrieve2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/`
}

export const batchExportsRunsRetrieve2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRunsRetrieve2Response> => {
    return apiMutator<batchExportsRunsRetrieve2Response>(
        getBatchExportsRunsRetrieve2Url(projectId, batchExportId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Cancel a batch export run.
 */
export type batchExportsRunsCancelCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsRunsCancelCreate2ResponseSuccess = batchExportsRunsCancelCreate2Response200 & {
    headers: Headers
}
export type batchExportsRunsCancelCreate2Response = batchExportsRunsCancelCreate2ResponseSuccess

export const getBatchExportsRunsCancelCreate2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/cancel/`
}

export const batchExportsRunsCancelCreate2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<batchExportsRunsCancelCreate2Response> => {
    return apiMutator<batchExportsRunsCancelCreate2Response>(
        getBatchExportsRunsCancelCreate2Url(projectId, batchExportId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportRunApi),
        }
    )
}

export type batchExportsRunsLogsRetrieve2Response200 = {
    data: void
    status: 200
}

export type batchExportsRunsLogsRetrieve2ResponseSuccess = batchExportsRunsLogsRetrieve2Response200 & {
    headers: Headers
}
export type batchExportsRunsLogsRetrieve2Response = batchExportsRunsLogsRetrieve2ResponseSuccess

export const getBatchExportsRunsLogsRetrieve2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/logs/`
}

export const batchExportsRunsLogsRetrieve2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRunsLogsRetrieve2Response> => {
    return apiMutator<batchExportsRunsLogsRetrieve2Response>(
        getBatchExportsRunsLogsRetrieve2Url(projectId, batchExportId, id),
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
export type batchExportsRunsRetryCreate2Response200 = {
    data: void
    status: 200
}

export type batchExportsRunsRetryCreate2ResponseSuccess = batchExportsRunsRetryCreate2Response200 & {
    headers: Headers
}
export type batchExportsRunsRetryCreate2Response = batchExportsRunsRetryCreate2ResponseSuccess

export const getBatchExportsRunsRetryCreate2Url = (projectId: string, batchExportId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${batchExportId}/runs/${id}/retry/`
}

export const batchExportsRunsRetryCreate2 = async (
    projectId: string,
    batchExportId: string,
    id: string,
    batchExportRunApi: NonReadonly<BatchExportRunApi>,
    options?: RequestInit
): Promise<batchExportsRunsRetryCreate2Response> => {
    return apiMutator<batchExportsRunsRetryCreate2Response>(
        getBatchExportsRunsRetryCreate2Url(projectId, batchExportId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchExportRunApi),
        }
    )
}

export type batchExportsRetrieve3Response200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsRetrieve3ResponseSuccess = batchExportsRetrieve3Response200 & {
    headers: Headers
}
export type batchExportsRetrieve3Response = batchExportsRetrieve3ResponseSuccess

export const getBatchExportsRetrieve3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsRetrieve3 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsRetrieve3Response> => {
    return apiMutator<batchExportsRetrieve3Response>(getBatchExportsRetrieve3Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type batchExportsUpdate3Response200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsUpdate3ResponseSuccess = batchExportsUpdate3Response200 & {
    headers: Headers
}
export type batchExportsUpdate3Response = batchExportsUpdate3ResponseSuccess

export const getBatchExportsUpdate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsUpdate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUpdate3Response> => {
    return apiMutator<batchExportsUpdate3Response>(getBatchExportsUpdate3Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsPartialUpdate3Response200 = {
    data: BatchExportApi
    status: 200
}

export type batchExportsPartialUpdate3ResponseSuccess = batchExportsPartialUpdate3Response200 & {
    headers: Headers
}
export type batchExportsPartialUpdate3Response = batchExportsPartialUpdate3ResponseSuccess

export const getBatchExportsPartialUpdate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsPartialUpdate3 = async (
    projectId: string,
    id: string,
    patchedBatchExportApi: NonReadonly<PatchedBatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPartialUpdate3Response> => {
    return apiMutator<batchExportsPartialUpdate3Response>(getBatchExportsPartialUpdate3Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBatchExportApi),
    })
}

export type batchExportsDestroy3Response204 = {
    data: void
    status: 204
}

export type batchExportsDestroy3ResponseSuccess = batchExportsDestroy3Response204 & {
    headers: Headers
}
export type batchExportsDestroy3Response = batchExportsDestroy3ResponseSuccess

export const getBatchExportsDestroy3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/`
}

export const batchExportsDestroy3 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsDestroy3Response> => {
    return apiMutator<batchExportsDestroy3Response>(getBatchExportsDestroy3Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a backfill for a BatchExport.

Note: This endpoint is deprecated. Please use POST /batch_exports/<id>/backfills/ instead.
 */
export type batchExportsBackfillCreate3Response200 = {
    data: void
    status: 200
}

export type batchExportsBackfillCreate3ResponseSuccess = batchExportsBackfillCreate3Response200 & {
    headers: Headers
}
export type batchExportsBackfillCreate3Response = batchExportsBackfillCreate3ResponseSuccess

export const getBatchExportsBackfillCreate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/backfill/`
}

export const batchExportsBackfillCreate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsBackfillCreate3Response> => {
    return apiMutator<batchExportsBackfillCreate3Response>(getBatchExportsBackfillCreate3Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsLogsRetrieve3Response200 = {
    data: void
    status: 200
}

export type batchExportsLogsRetrieve3ResponseSuccess = batchExportsLogsRetrieve3Response200 & {
    headers: Headers
}
export type batchExportsLogsRetrieve3Response = batchExportsLogsRetrieve3ResponseSuccess

export const getBatchExportsLogsRetrieve3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/logs/`
}

export const batchExportsLogsRetrieve3 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<batchExportsLogsRetrieve3Response> => {
    return apiMutator<batchExportsLogsRetrieve3Response>(getBatchExportsLogsRetrieve3Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Pause a BatchExport.
 */
export type batchExportsPauseCreate3Response200 = {
    data: void
    status: 200
}

export type batchExportsPauseCreate3ResponseSuccess = batchExportsPauseCreate3Response200 & {
    headers: Headers
}
export type batchExportsPauseCreate3Response = batchExportsPauseCreate3ResponseSuccess

export const getBatchExportsPauseCreate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/pause/`
}

export const batchExportsPauseCreate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsPauseCreate3Response> => {
    return apiMutator<batchExportsPauseCreate3Response>(getBatchExportsPauseCreate3Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRunTestStepCreate3Response200 = {
    data: void
    status: 200
}

export type batchExportsRunTestStepCreate3ResponseSuccess = batchExportsRunTestStepCreate3Response200 & {
    headers: Headers
}
export type batchExportsRunTestStepCreate3Response = batchExportsRunTestStepCreate3ResponseSuccess

export const getBatchExportsRunTestStepCreate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/run_test_step/`
}

export const batchExportsRunTestStepCreate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepCreate3Response> => {
    return apiMutator<batchExportsRunTestStepCreate3Response>(getBatchExportsRunTestStepCreate3Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

/**
 * Unpause a BatchExport.
 */
export type batchExportsUnpauseCreate3Response200 = {
    data: void
    status: 200
}

export type batchExportsUnpauseCreate3ResponseSuccess = batchExportsUnpauseCreate3Response200 & {
    headers: Headers
}
export type batchExportsUnpauseCreate3Response = batchExportsUnpauseCreate3ResponseSuccess

export const getBatchExportsUnpauseCreate3Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/batch_exports/${id}/unpause/`
}

export const batchExportsUnpauseCreate3 = async (
    projectId: string,
    id: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsUnpauseCreate3Response> => {
    return apiMutator<batchExportsUnpauseCreate3Response>(getBatchExportsUnpauseCreate3Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsRunTestStepNewCreate3Response200 = {
    data: void
    status: 200
}

export type batchExportsRunTestStepNewCreate3ResponseSuccess = batchExportsRunTestStepNewCreate3Response200 & {
    headers: Headers
}
export type batchExportsRunTestStepNewCreate3Response = batchExportsRunTestStepNewCreate3ResponseSuccess

export const getBatchExportsRunTestStepNewCreate3Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/run_test_step_new/`
}

export const batchExportsRunTestStepNewCreate3 = async (
    projectId: string,
    batchExportApi: NonReadonly<BatchExportApi>,
    options?: RequestInit
): Promise<batchExportsRunTestStepNewCreate3Response> => {
    return apiMutator<batchExportsRunTestStepNewCreate3Response>(getBatchExportsRunTestStepNewCreate3Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchExportApi),
    })
}

export type batchExportsTestRetrieve3Response200 = {
    data: void
    status: 200
}

export type batchExportsTestRetrieve3ResponseSuccess = batchExportsTestRetrieve3Response200 & {
    headers: Headers
}
export type batchExportsTestRetrieve3Response = batchExportsTestRetrieve3ResponseSuccess

export const getBatchExportsTestRetrieve3Url = (projectId: string) => {
    return `/api/projects/${projectId}/batch_exports/test/`
}

export const batchExportsTestRetrieve3 = async (
    projectId: string,
    options?: RequestInit
): Promise<batchExportsTestRetrieve3Response> => {
    return apiMutator<batchExportsTestRetrieve3Response>(getBatchExportsTestRetrieve3Url(projectId), {
        ...options,
        method: 'GET',
    })
}
