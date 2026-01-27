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
    DataModelingJobApi,
    DataModelingJobsListParams,
    DataWarehouseSavedQueryApi,
    DataWarehouseSavedQueryDraftApi,
    EnvironmentsDataModelingJobsListParams,
    EnvironmentsExternalDataSchemasListParams,
    EnvironmentsExternalDataSourcesListParams,
    EnvironmentsWarehouseSavedQueriesListParams,
    EnvironmentsWarehouseSavedQueryDraftsListParams,
    EnvironmentsWarehouseTablesListParams,
    EnvironmentsWarehouseViewLinkListParams,
    EnvironmentsWarehouseViewLinksListParams,
    ExternalDataSchemaApi,
    ExternalDataSchemasListParams,
    ExternalDataSourceSerializersApi,
    ExternalDataSourcesListParams,
    PaginatedDataModelingJobListApi,
    PaginatedDataWarehouseModelPathListApi,
    PaginatedDataWarehouseSavedQueryDraftListApi,
    PaginatedDataWarehouseSavedQueryMinimalListApi,
    PaginatedExternalDataSchemaListApi,
    PaginatedExternalDataSourceSerializersListApi,
    PaginatedQueryTabStateListApi,
    PaginatedTableListApi,
    PaginatedViewLinkListApi,
    PatchedDataWarehouseSavedQueryApi,
    PatchedDataWarehouseSavedQueryDraftApi,
    PatchedExternalDataSourceSerializersApi,
    PatchedQueryTabStateApi,
    QueryTabStateApi,
    QueryTabStateListParams,
    TableApi,
    ViewLinkApi,
    ViewLinkValidationApi,
    WarehouseModelPathsListParams,
    WarehouseSavedQueriesListParams,
    WarehouseTablesListParams,
    WarehouseViewLinkListParams,
    WarehouseViewLinksListParams,
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

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export type environmentsDataModelingJobsListResponse200 = {
    data: PaginatedDataModelingJobListApi
    status: 200
}

export type environmentsDataModelingJobsListResponseSuccess = environmentsDataModelingJobsListResponse200 & {
    headers: Headers
}
export type environmentsDataModelingJobsListResponse = environmentsDataModelingJobsListResponseSuccess

export const getEnvironmentsDataModelingJobsListUrl = (
    projectId: string,
    params?: EnvironmentsDataModelingJobsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/data_modeling_jobs/?${stringifiedParams}`
        : `/api/environments/${projectId}/data_modeling_jobs/`
}

export const environmentsDataModelingJobsList = async (
    projectId: string,
    params?: EnvironmentsDataModelingJobsListParams,
    options?: RequestInit
): Promise<environmentsDataModelingJobsListResponse> => {
    return apiMutator<environmentsDataModelingJobsListResponse>(
        getEnvironmentsDataModelingJobsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export type environmentsDataModelingJobsRetrieveResponse200 = {
    data: DataModelingJobApi
    status: 200
}

export type environmentsDataModelingJobsRetrieveResponseSuccess = environmentsDataModelingJobsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsDataModelingJobsRetrieveResponse = environmentsDataModelingJobsRetrieveResponseSuccess

export const getEnvironmentsDataModelingJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/data_modeling_jobs/${id}/`
}

export const environmentsDataModelingJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsDataModelingJobsRetrieveResponse> => {
    return apiMutator<environmentsDataModelingJobsRetrieveResponse>(
        getEnvironmentsDataModelingJobsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns completed/non-running activities (jobs with status 'Completed').
Supports pagination and cutoff time filtering.
 */
export type environmentsDataWarehouseCompletedActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsDataWarehouseCompletedActivityRetrieveResponseSuccess =
    environmentsDataWarehouseCompletedActivityRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsDataWarehouseCompletedActivityRetrieveResponse =
    environmentsDataWarehouseCompletedActivityRetrieveResponseSuccess

export const getEnvironmentsDataWarehouseCompletedActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/completed_activity/`
}

export const environmentsDataWarehouseCompletedActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsDataWarehouseCompletedActivityRetrieveResponse> => {
    return apiMutator<environmentsDataWarehouseCompletedActivityRetrieveResponse>(
        getEnvironmentsDataWarehouseCompletedActivityRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
Includes: materializations, syncs, sources, destinations, and transformations.
 */
export type environmentsDataWarehouseDataHealthIssuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsDataWarehouseDataHealthIssuesRetrieveResponseSuccess =
    environmentsDataWarehouseDataHealthIssuesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsDataWarehouseDataHealthIssuesRetrieveResponse =
    environmentsDataWarehouseDataHealthIssuesRetrieveResponseSuccess

export const getEnvironmentsDataWarehouseDataHealthIssuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/data_health_issues/`
}

export const environmentsDataWarehouseDataHealthIssuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsDataWarehouseDataHealthIssuesRetrieveResponse> => {
    return apiMutator<environmentsDataWarehouseDataHealthIssuesRetrieveResponse>(
        getEnvironmentsDataWarehouseDataHealthIssuesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns success and failed job statistics for the last 1, 7, or 30 days.
Query parameter 'days' can be 1, 7, or 30 (default: 7).
 */
export type environmentsDataWarehouseJobStatsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsDataWarehouseJobStatsRetrieveResponseSuccess =
    environmentsDataWarehouseJobStatsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsDataWarehouseJobStatsRetrieveResponse = environmentsDataWarehouseJobStatsRetrieveResponseSuccess

export const getEnvironmentsDataWarehouseJobStatsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/job_stats/`
}

export const environmentsDataWarehouseJobStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsDataWarehouseJobStatsRetrieveResponse> => {
    return apiMutator<environmentsDataWarehouseJobStatsRetrieveResponse>(
        getEnvironmentsDataWarehouseJobStatsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * API endpoints for data warehouse aggregate statistics and operations.
 */
export type environmentsDataWarehousePropertyValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsDataWarehousePropertyValuesRetrieveResponseSuccess =
    environmentsDataWarehousePropertyValuesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsDataWarehousePropertyValuesRetrieveResponse =
    environmentsDataWarehousePropertyValuesRetrieveResponseSuccess

export const getEnvironmentsDataWarehousePropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/property_values/`
}

export const environmentsDataWarehousePropertyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsDataWarehousePropertyValuesRetrieveResponse> => {
    return apiMutator<environmentsDataWarehousePropertyValuesRetrieveResponse>(
        getEnvironmentsDataWarehousePropertyValuesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns currently running activities (jobs with status 'Running').
Supports pagination and cutoff time filtering.
 */
export type environmentsDataWarehouseRunningActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsDataWarehouseRunningActivityRetrieveResponseSuccess =
    environmentsDataWarehouseRunningActivityRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsDataWarehouseRunningActivityRetrieveResponse =
    environmentsDataWarehouseRunningActivityRetrieveResponseSuccess

export const getEnvironmentsDataWarehouseRunningActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/running_activity/`
}

export const environmentsDataWarehouseRunningActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsDataWarehouseRunningActivityRetrieveResponse> => {
    return apiMutator<environmentsDataWarehouseRunningActivityRetrieveResponse>(
        getEnvironmentsDataWarehouseRunningActivityRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns aggregated statistics for the data warehouse total rows processed within the current billing period.
Used by the frontend data warehouse scene to display usage information.
 */
export type environmentsDataWarehouseTotalRowsStatsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsDataWarehouseTotalRowsStatsRetrieveResponseSuccess =
    environmentsDataWarehouseTotalRowsStatsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsDataWarehouseTotalRowsStatsRetrieveResponse =
    environmentsDataWarehouseTotalRowsStatsRetrieveResponseSuccess

export const getEnvironmentsDataWarehouseTotalRowsStatsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/total_rows_stats/`
}

export const environmentsDataWarehouseTotalRowsStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsDataWarehouseTotalRowsStatsRetrieveResponse> => {
    return apiMutator<environmentsDataWarehouseTotalRowsStatsRetrieveResponse>(
        getEnvironmentsDataWarehouseTotalRowsStatsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsExternalDataSchemasListResponse200 = {
    data: PaginatedExternalDataSchemaListApi
    status: 200
}

export type environmentsExternalDataSchemasListResponseSuccess = environmentsExternalDataSchemasListResponse200 & {
    headers: Headers
}
export type environmentsExternalDataSchemasListResponse = environmentsExternalDataSchemasListResponseSuccess

export const getEnvironmentsExternalDataSchemasListUrl = (
    projectId: string,
    params?: EnvironmentsExternalDataSchemasListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/external_data_schemas/?${stringifiedParams}`
        : `/api/environments/${projectId}/external_data_schemas/`
}

export const environmentsExternalDataSchemasList = async (
    projectId: string,
    params?: EnvironmentsExternalDataSchemasListParams,
    options?: RequestInit
): Promise<environmentsExternalDataSchemasListResponse> => {
    return apiMutator<environmentsExternalDataSchemasListResponse>(
        getEnvironmentsExternalDataSchemasListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsExternalDataSchemasCreateResponse201 = {
    data: ExternalDataSchemaApi
    status: 201
}

export type environmentsExternalDataSchemasCreateResponseSuccess = environmentsExternalDataSchemasCreateResponse201 & {
    headers: Headers
}
export type environmentsExternalDataSchemasCreateResponse = environmentsExternalDataSchemasCreateResponseSuccess

export const getEnvironmentsExternalDataSchemasCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_schemas/`
}

export const environmentsExternalDataSchemasCreate = async (
    projectId: string,
    externalDataSchemaApi: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<environmentsExternalDataSchemasCreateResponse> => {
    return apiMutator<environmentsExternalDataSchemasCreateResponse>(
        getEnvironmentsExternalDataSchemasCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(externalDataSchemaApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesListResponse200 = {
    data: PaginatedExternalDataSourceSerializersListApi
    status: 200
}

export type environmentsExternalDataSourcesListResponseSuccess = environmentsExternalDataSourcesListResponse200 & {
    headers: Headers
}
export type environmentsExternalDataSourcesListResponse = environmentsExternalDataSourcesListResponseSuccess

export const getEnvironmentsExternalDataSourcesListUrl = (
    projectId: string,
    params?: EnvironmentsExternalDataSourcesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/external_data_sources/?${stringifiedParams}`
        : `/api/environments/${projectId}/external_data_sources/`
}

export const environmentsExternalDataSourcesList = async (
    projectId: string,
    params?: EnvironmentsExternalDataSourcesListParams,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesListResponse> => {
    return apiMutator<environmentsExternalDataSourcesListResponse>(
        getEnvironmentsExternalDataSourcesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesCreateResponse201 = {
    data: ExternalDataSourceSerializersApi
    status: 201
}

export type environmentsExternalDataSourcesCreateResponseSuccess = environmentsExternalDataSourcesCreateResponse201 & {
    headers: Headers
}
export type environmentsExternalDataSourcesCreateResponse = environmentsExternalDataSourcesCreateResponseSuccess

export const getEnvironmentsExternalDataSourcesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/`
}

export const environmentsExternalDataSourcesCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesCreateResponse> => {
    return apiMutator<environmentsExternalDataSourcesCreateResponse>(
        getEnvironmentsExternalDataSourcesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(externalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesRetrieveResponse200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type environmentsExternalDataSourcesRetrieveResponseSuccess =
    environmentsExternalDataSourcesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesRetrieveResponse = environmentsExternalDataSourcesRetrieveResponseSuccess

export const getEnvironmentsExternalDataSourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const environmentsExternalDataSourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesRetrieveResponse> => {
    return apiMutator<environmentsExternalDataSourcesRetrieveResponse>(
        getEnvironmentsExternalDataSourcesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesUpdateResponse200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type environmentsExternalDataSourcesUpdateResponseSuccess = environmentsExternalDataSourcesUpdateResponse200 & {
    headers: Headers
}
export type environmentsExternalDataSourcesUpdateResponse = environmentsExternalDataSourcesUpdateResponseSuccess

export const getEnvironmentsExternalDataSourcesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const environmentsExternalDataSourcesUpdate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesUpdateResponse> => {
    return apiMutator<environmentsExternalDataSourcesUpdateResponse>(
        getEnvironmentsExternalDataSourcesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(externalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesPartialUpdateResponse200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type environmentsExternalDataSourcesPartialUpdateResponseSuccess =
    environmentsExternalDataSourcesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesPartialUpdateResponse =
    environmentsExternalDataSourcesPartialUpdateResponseSuccess

export const getEnvironmentsExternalDataSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const environmentsExternalDataSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesPartialUpdateResponse> => {
    return apiMutator<environmentsExternalDataSourcesPartialUpdateResponse>(
        getEnvironmentsExternalDataSourcesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedExternalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsExternalDataSourcesDestroyResponseSuccess =
    environmentsExternalDataSourcesDestroyResponse204 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesDestroyResponse = environmentsExternalDataSourcesDestroyResponseSuccess

export const getEnvironmentsExternalDataSourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const environmentsExternalDataSourcesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesDestroyResponse> => {
    return apiMutator<environmentsExternalDataSourcesDestroyResponse>(
        getEnvironmentsExternalDataSourcesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesJobsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsExternalDataSourcesJobsRetrieveResponseSuccess =
    environmentsExternalDataSourcesJobsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesJobsRetrieveResponse =
    environmentsExternalDataSourcesJobsRetrieveResponseSuccess

export const getEnvironmentsExternalDataSourcesJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/jobs/`
}

export const environmentsExternalDataSourcesJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesJobsRetrieveResponse> => {
    return apiMutator<environmentsExternalDataSourcesJobsRetrieveResponse>(
        getEnvironmentsExternalDataSourcesJobsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesReloadCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsExternalDataSourcesReloadCreateResponseSuccess =
    environmentsExternalDataSourcesReloadCreateResponse200 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesReloadCreateResponse =
    environmentsExternalDataSourcesReloadCreateResponseSuccess

export const getEnvironmentsExternalDataSourcesReloadCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/reload/`
}

export const environmentsExternalDataSourcesReloadCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesReloadCreateResponse> => {
    return apiMutator<environmentsExternalDataSourcesReloadCreateResponse>(
        getEnvironmentsExternalDataSourcesReloadCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(externalDataSourceSerializersApi),
        }
    )
}

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export type environmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateResponseSuccess =
    environmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse =
    environmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateResponseSuccess

export const getEnvironmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl = (
    projectId: string,
    id: string
) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/revenue_analytics_config/`
}

export const environmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse> => {
    return apiMutator<environmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse>(
        getEnvironmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedExternalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesDatabaseSchemaCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsExternalDataSourcesDatabaseSchemaCreateResponseSuccess =
    environmentsExternalDataSourcesDatabaseSchemaCreateResponse200 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesDatabaseSchemaCreateResponse =
    environmentsExternalDataSourcesDatabaseSchemaCreateResponseSuccess

export const getEnvironmentsExternalDataSourcesDatabaseSchemaCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/database_schema/`
}

export const environmentsExternalDataSourcesDatabaseSchemaCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesDatabaseSchemaCreateResponse> => {
    return apiMutator<environmentsExternalDataSourcesDatabaseSchemaCreateResponse>(
        getEnvironmentsExternalDataSourcesDatabaseSchemaCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(externalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesSourcePrefixCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsExternalDataSourcesSourcePrefixCreateResponseSuccess =
    environmentsExternalDataSourcesSourcePrefixCreateResponse200 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesSourcePrefixCreateResponse =
    environmentsExternalDataSourcesSourcePrefixCreateResponseSuccess

export const getEnvironmentsExternalDataSourcesSourcePrefixCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/source_prefix/`
}

export const environmentsExternalDataSourcesSourcePrefixCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesSourcePrefixCreateResponse> => {
    return apiMutator<environmentsExternalDataSourcesSourcePrefixCreateResponse>(
        getEnvironmentsExternalDataSourcesSourcePrefixCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(externalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type environmentsExternalDataSourcesWizardRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsExternalDataSourcesWizardRetrieveResponseSuccess =
    environmentsExternalDataSourcesWizardRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsExternalDataSourcesWizardRetrieveResponse =
    environmentsExternalDataSourcesWizardRetrieveResponseSuccess

export const getEnvironmentsExternalDataSourcesWizardRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/wizard/`
}

export const environmentsExternalDataSourcesWizardRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsExternalDataSourcesWizardRetrieveResponse> => {
    return apiMutator<environmentsExternalDataSourcesWizardRetrieveResponse>(
        getEnvironmentsExternalDataSourcesWizardRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsFixHogqlRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsFixHogqlRetrieveResponseSuccess = environmentsFixHogqlRetrieveResponse200 & {
    headers: Headers
}
export type environmentsFixHogqlRetrieveResponse = environmentsFixHogqlRetrieveResponseSuccess

export const getEnvironmentsFixHogqlRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/fix_hogql/`
}

export const environmentsFixHogqlRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsFixHogqlRetrieveResponse> => {
    return apiMutator<environmentsFixHogqlRetrieveResponse>(getEnvironmentsFixHogqlRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type environmentsFixHogqlCreateResponse201 = {
    data: void
    status: 201
}

export type environmentsFixHogqlCreateResponseSuccess = environmentsFixHogqlCreateResponse201 & {
    headers: Headers
}
export type environmentsFixHogqlCreateResponse = environmentsFixHogqlCreateResponseSuccess

export const getEnvironmentsFixHogqlCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/fix_hogql/`
}

export const environmentsFixHogqlCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsFixHogqlCreateResponse> => {
    return apiMutator<environmentsFixHogqlCreateResponse>(getEnvironmentsFixHogqlCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type environmentsLineageGetUpstreamRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsLineageGetUpstreamRetrieveResponseSuccess =
    environmentsLineageGetUpstreamRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsLineageGetUpstreamRetrieveResponse = environmentsLineageGetUpstreamRetrieveResponseSuccess

export const getEnvironmentsLineageGetUpstreamRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/lineage/get_upstream/`
}

export const environmentsLineageGetUpstreamRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLineageGetUpstreamRetrieveResponse> => {
    return apiMutator<environmentsLineageGetUpstreamRetrieveResponse>(
        getEnvironmentsLineageGetUpstreamRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get all views associated with a specific managed viewset.
GET /api/environments/{team_id}/managed_viewsets/{kind}/
 */
export type environmentsManagedViewsetsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsManagedViewsetsRetrieveResponseSuccess = environmentsManagedViewsetsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsManagedViewsetsRetrieveResponse = environmentsManagedViewsetsRetrieveResponseSuccess

export const getEnvironmentsManagedViewsetsRetrieveUrl = (projectId: string, kind: 'revenue_analytics') => {
    return `/api/environments/${projectId}/managed_viewsets/${kind}/`
}

export const environmentsManagedViewsetsRetrieve = async (
    projectId: string,
    kind: 'revenue_analytics',
    options?: RequestInit
): Promise<environmentsManagedViewsetsRetrieveResponse> => {
    return apiMutator<environmentsManagedViewsetsRetrieveResponse>(
        getEnvironmentsManagedViewsetsRetrieveUrl(projectId, kind),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Enable or disable a managed viewset by kind.
PUT /api/environments/{team_id}/managed_viewsets/{kind}/ with body {"enabled": true/false}
 */
export type environmentsManagedViewsetsUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsManagedViewsetsUpdateResponseSuccess = environmentsManagedViewsetsUpdateResponse200 & {
    headers: Headers
}
export type environmentsManagedViewsetsUpdateResponse = environmentsManagedViewsetsUpdateResponseSuccess

export const getEnvironmentsManagedViewsetsUpdateUrl = (projectId: string, kind: 'revenue_analytics') => {
    return `/api/environments/${projectId}/managed_viewsets/${kind}/`
}

export const environmentsManagedViewsetsUpdate = async (
    projectId: string,
    kind: 'revenue_analytics',
    options?: RequestInit
): Promise<environmentsManagedViewsetsUpdateResponse> => {
    return apiMutator<environmentsManagedViewsetsUpdateResponse>(
        getEnvironmentsManagedViewsetsUpdateUrl(projectId, kind),
        {
            ...options,
            method: 'PUT',
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseSavedQueriesListResponse200 = {
    data: PaginatedDataWarehouseSavedQueryMinimalListApi
    status: 200
}

export type environmentsWarehouseSavedQueriesListResponseSuccess = environmentsWarehouseSavedQueriesListResponse200 & {
    headers: Headers
}
export type environmentsWarehouseSavedQueriesListResponse = environmentsWarehouseSavedQueriesListResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesListUrl = (
    projectId: string,
    params?: EnvironmentsWarehouseSavedQueriesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/warehouse_saved_queries/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_saved_queries/`
}

export const environmentsWarehouseSavedQueriesList = async (
    projectId: string,
    params?: EnvironmentsWarehouseSavedQueriesListParams,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesListResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesListResponse>(
        getEnvironmentsWarehouseSavedQueriesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseSavedQueriesCreateResponse201 = {
    data: DataWarehouseSavedQueryApi
    status: 201
}

export type environmentsWarehouseSavedQueriesCreateResponseSuccess =
    environmentsWarehouseSavedQueriesCreateResponse201 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesCreateResponse = environmentsWarehouseSavedQueriesCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/`
}

export const environmentsWarehouseSavedQueriesCreate = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesCreateResponse>(
        getEnvironmentsWarehouseSavedQueriesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseSavedQueriesRetrieveResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesRetrieveResponseSuccess =
    environmentsWarehouseSavedQueriesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesRetrieveResponse = environmentsWarehouseSavedQueriesRetrieveResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const environmentsWarehouseSavedQueriesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesRetrieveResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesRetrieveResponse>(
        getEnvironmentsWarehouseSavedQueriesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseSavedQueriesUpdateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesUpdateResponseSuccess =
    environmentsWarehouseSavedQueriesUpdateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesUpdateResponse = environmentsWarehouseSavedQueriesUpdateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const environmentsWarehouseSavedQueriesUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesUpdateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesUpdateResponse>(
        getEnvironmentsWarehouseSavedQueriesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseSavedQueriesPartialUpdateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesPartialUpdateResponseSuccess =
    environmentsWarehouseSavedQueriesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesPartialUpdateResponse =
    environmentsWarehouseSavedQueriesPartialUpdateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const environmentsWarehouseSavedQueriesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryApi: NonReadonly<PatchedDataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesPartialUpdateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesPartialUpdateResponse>(
        getEnvironmentsWarehouseSavedQueriesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseSavedQueriesDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsWarehouseSavedQueriesDestroyResponseSuccess =
    environmentsWarehouseSavedQueriesDestroyResponse204 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesDestroyResponse = environmentsWarehouseSavedQueriesDestroyResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const environmentsWarehouseSavedQueriesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesDestroyResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesDestroyResponse>(
        getEnvironmentsWarehouseSavedQueriesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseSavedQueriesActivityRetrieveResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesActivityRetrieveResponseSuccess =
    environmentsWarehouseSavedQueriesActivityRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesActivityRetrieveResponse =
    environmentsWarehouseSavedQueriesActivityRetrieveResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesActivityRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/activity/`
}

export const environmentsWarehouseSavedQueriesActivityRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesActivityRetrieveResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesActivityRetrieveResponse>(
        getEnvironmentsWarehouseSavedQueriesActivityRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Return the ancestors of this saved query.

By default, we return the immediate parents. The `level` parameter can be used to
look further back into the ancestor tree. If `level` overshoots (i.e. points to only
ancestors beyond the root), we return an empty list.
 */
export type environmentsWarehouseSavedQueriesAncestorsCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesAncestorsCreateResponseSuccess =
    environmentsWarehouseSavedQueriesAncestorsCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesAncestorsCreateResponse =
    environmentsWarehouseSavedQueriesAncestorsCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesAncestorsCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/ancestors/`
}

export const environmentsWarehouseSavedQueriesAncestorsCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesAncestorsCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesAncestorsCreateResponse>(
        getEnvironmentsWarehouseSavedQueriesAncestorsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Cancel a running saved query workflow.
 */
export type environmentsWarehouseSavedQueriesCancelCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesCancelCreateResponseSuccess =
    environmentsWarehouseSavedQueriesCancelCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesCancelCreateResponse =
    environmentsWarehouseSavedQueriesCancelCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/cancel/`
}

export const environmentsWarehouseSavedQueriesCancelCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesCancelCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesCancelCreateResponse>(
        getEnvironmentsWarehouseSavedQueriesCancelCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Return the count of immediate upstream and downstream dependencies for this saved query.
 */
export type environmentsWarehouseSavedQueriesDependenciesRetrieveResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesDependenciesRetrieveResponseSuccess =
    environmentsWarehouseSavedQueriesDependenciesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesDependenciesRetrieveResponse =
    environmentsWarehouseSavedQueriesDependenciesRetrieveResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesDependenciesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/dependencies/`
}

export const environmentsWarehouseSavedQueriesDependenciesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesDependenciesRetrieveResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesDependenciesRetrieveResponse>(
        getEnvironmentsWarehouseSavedQueriesDependenciesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Return the descendants of this saved query.

By default, we return the immediate children. The `level` parameter can be used to
look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
descendants further than a leaf), we return an empty list.
 */
export type environmentsWarehouseSavedQueriesDescendantsCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesDescendantsCreateResponseSuccess =
    environmentsWarehouseSavedQueriesDescendantsCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesDescendantsCreateResponse =
    environmentsWarehouseSavedQueriesDescendantsCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesDescendantsCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/descendants/`
}

export const environmentsWarehouseSavedQueriesDescendantsCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesDescendantsCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesDescendantsCreateResponse>(
        getEnvironmentsWarehouseSavedQueriesDescendantsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export type environmentsWarehouseSavedQueriesMaterializeCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesMaterializeCreateResponseSuccess =
    environmentsWarehouseSavedQueriesMaterializeCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesMaterializeCreateResponse =
    environmentsWarehouseSavedQueriesMaterializeCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesMaterializeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/materialize/`
}

export const environmentsWarehouseSavedQueriesMaterializeCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesMaterializeCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesMaterializeCreateResponse>(
        getEnvironmentsWarehouseSavedQueriesMaterializeCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Undo materialization, revert back to the original view.
(i.e. delete the materialized table and the schedule)
 */
export type environmentsWarehouseSavedQueriesRevertMaterializationCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesRevertMaterializationCreateResponseSuccess =
    environmentsWarehouseSavedQueriesRevertMaterializationCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesRevertMaterializationCreateResponse =
    environmentsWarehouseSavedQueriesRevertMaterializationCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesRevertMaterializationCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
}

export const environmentsWarehouseSavedQueriesRevertMaterializationCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesRevertMaterializationCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesRevertMaterializationCreateResponse>(
        getEnvironmentsWarehouseSavedQueriesRevertMaterializationCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Run this saved query.
 */
export type environmentsWarehouseSavedQueriesRunCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesRunCreateResponseSuccess =
    environmentsWarehouseSavedQueriesRunCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesRunCreateResponse =
    environmentsWarehouseSavedQueriesRunCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesRunCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/run/`
}

export const environmentsWarehouseSavedQueriesRunCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesRunCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesRunCreateResponse>(
        getEnvironmentsWarehouseSavedQueriesRunCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export type environmentsWarehouseSavedQueriesRunHistoryRetrieveResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesRunHistoryRetrieveResponseSuccess =
    environmentsWarehouseSavedQueriesRunHistoryRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesRunHistoryRetrieveResponse =
    environmentsWarehouseSavedQueriesRunHistoryRetrieveResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesRunHistoryRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/run_history/`
}

export const environmentsWarehouseSavedQueriesRunHistoryRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesRunHistoryRetrieveResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesRunHistoryRetrieveResponse>(
        getEnvironmentsWarehouseSavedQueriesRunHistoryRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Resume paused materialization schedules for multiple matviews.

Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
export type environmentsWarehouseSavedQueriesResumeSchedulesCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type environmentsWarehouseSavedQueriesResumeSchedulesCreateResponseSuccess =
    environmentsWarehouseSavedQueriesResumeSchedulesCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueriesResumeSchedulesCreateResponse =
    environmentsWarehouseSavedQueriesResumeSchedulesCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueriesResumeSchedulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/resume_schedules/`
}

export const environmentsWarehouseSavedQueriesResumeSchedulesCreate = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueriesResumeSchedulesCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueriesResumeSchedulesCreateResponse>(
        getEnvironmentsWarehouseSavedQueriesResumeSchedulesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

export type environmentsWarehouseSavedQueryDraftsListResponse200 = {
    data: PaginatedDataWarehouseSavedQueryDraftListApi
    status: 200
}

export type environmentsWarehouseSavedQueryDraftsListResponseSuccess =
    environmentsWarehouseSavedQueryDraftsListResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueryDraftsListResponse = environmentsWarehouseSavedQueryDraftsListResponseSuccess

export const getEnvironmentsWarehouseSavedQueryDraftsListUrl = (
    projectId: string,
    params?: EnvironmentsWarehouseSavedQueryDraftsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/warehouse_saved_query_drafts/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_saved_query_drafts/`
}

export const environmentsWarehouseSavedQueryDraftsList = async (
    projectId: string,
    params?: EnvironmentsWarehouseSavedQueryDraftsListParams,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueryDraftsListResponse> => {
    return apiMutator<environmentsWarehouseSavedQueryDraftsListResponse>(
        getEnvironmentsWarehouseSavedQueryDraftsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsWarehouseSavedQueryDraftsCreateResponse201 = {
    data: DataWarehouseSavedQueryDraftApi
    status: 201
}

export type environmentsWarehouseSavedQueryDraftsCreateResponseSuccess =
    environmentsWarehouseSavedQueryDraftsCreateResponse201 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueryDraftsCreateResponse =
    environmentsWarehouseSavedQueryDraftsCreateResponseSuccess

export const getEnvironmentsWarehouseSavedQueryDraftsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/`
}

export const environmentsWarehouseSavedQueryDraftsCreate = async (
    projectId: string,
    dataWarehouseSavedQueryDraftApi: NonReadonly<DataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueryDraftsCreateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueryDraftsCreateResponse>(
        getEnvironmentsWarehouseSavedQueryDraftsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryDraftApi),
        }
    )
}

export type environmentsWarehouseSavedQueryDraftsRetrieveResponse200 = {
    data: DataWarehouseSavedQueryDraftApi
    status: 200
}

export type environmentsWarehouseSavedQueryDraftsRetrieveResponseSuccess =
    environmentsWarehouseSavedQueryDraftsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueryDraftsRetrieveResponse =
    environmentsWarehouseSavedQueryDraftsRetrieveResponseSuccess

export const getEnvironmentsWarehouseSavedQueryDraftsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const environmentsWarehouseSavedQueryDraftsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueryDraftsRetrieveResponse> => {
    return apiMutator<environmentsWarehouseSavedQueryDraftsRetrieveResponse>(
        getEnvironmentsWarehouseSavedQueryDraftsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsWarehouseSavedQueryDraftsUpdateResponse200 = {
    data: DataWarehouseSavedQueryDraftApi
    status: 200
}

export type environmentsWarehouseSavedQueryDraftsUpdateResponseSuccess =
    environmentsWarehouseSavedQueryDraftsUpdateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueryDraftsUpdateResponse =
    environmentsWarehouseSavedQueryDraftsUpdateResponseSuccess

export const getEnvironmentsWarehouseSavedQueryDraftsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const environmentsWarehouseSavedQueryDraftsUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryDraftApi: NonReadonly<DataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueryDraftsUpdateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueryDraftsUpdateResponse>(
        getEnvironmentsWarehouseSavedQueryDraftsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryDraftApi),
        }
    )
}

export type environmentsWarehouseSavedQueryDraftsPartialUpdateResponse200 = {
    data: DataWarehouseSavedQueryDraftApi
    status: 200
}

export type environmentsWarehouseSavedQueryDraftsPartialUpdateResponseSuccess =
    environmentsWarehouseSavedQueryDraftsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueryDraftsPartialUpdateResponse =
    environmentsWarehouseSavedQueryDraftsPartialUpdateResponseSuccess

export const getEnvironmentsWarehouseSavedQueryDraftsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const environmentsWarehouseSavedQueryDraftsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryDraftApi: NonReadonly<PatchedDataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueryDraftsPartialUpdateResponse> => {
    return apiMutator<environmentsWarehouseSavedQueryDraftsPartialUpdateResponse>(
        getEnvironmentsWarehouseSavedQueryDraftsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDataWarehouseSavedQueryDraftApi),
        }
    )
}

export type environmentsWarehouseSavedQueryDraftsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsWarehouseSavedQueryDraftsDestroyResponseSuccess =
    environmentsWarehouseSavedQueryDraftsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsWarehouseSavedQueryDraftsDestroyResponse =
    environmentsWarehouseSavedQueryDraftsDestroyResponseSuccess

export const getEnvironmentsWarehouseSavedQueryDraftsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const environmentsWarehouseSavedQueryDraftsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsWarehouseSavedQueryDraftsDestroyResponse> => {
    return apiMutator<environmentsWarehouseSavedQueryDraftsDestroyResponse>(
        getEnvironmentsWarehouseSavedQueryDraftsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseTablesListResponse200 = {
    data: PaginatedTableListApi
    status: 200
}

export type environmentsWarehouseTablesListResponseSuccess = environmentsWarehouseTablesListResponse200 & {
    headers: Headers
}
export type environmentsWarehouseTablesListResponse = environmentsWarehouseTablesListResponseSuccess

export const getEnvironmentsWarehouseTablesListUrl = (
    projectId: string,
    params?: EnvironmentsWarehouseTablesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/warehouse_tables/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_tables/`
}

export const environmentsWarehouseTablesList = async (
    projectId: string,
    params?: EnvironmentsWarehouseTablesListParams,
    options?: RequestInit
): Promise<environmentsWarehouseTablesListResponse> => {
    return apiMutator<environmentsWarehouseTablesListResponse>(
        getEnvironmentsWarehouseTablesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseTablesCreateResponse201 = {
    data: TableApi
    status: 201
}

export type environmentsWarehouseTablesCreateResponseSuccess = environmentsWarehouseTablesCreateResponse201 & {
    headers: Headers
}
export type environmentsWarehouseTablesCreateResponse = environmentsWarehouseTablesCreateResponseSuccess

export const getEnvironmentsWarehouseTablesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_tables/`
}

export const environmentsWarehouseTablesCreate = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<environmentsWarehouseTablesCreateResponse> => {
    return apiMutator<environmentsWarehouseTablesCreateResponse>(getEnvironmentsWarehouseTablesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tableApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type environmentsWarehouseTablesFileCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsWarehouseTablesFileCreateResponseSuccess = environmentsWarehouseTablesFileCreateResponse200 & {
    headers: Headers
}
export type environmentsWarehouseTablesFileCreateResponse = environmentsWarehouseTablesFileCreateResponseSuccess

export const getEnvironmentsWarehouseTablesFileCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_tables/file/`
}

export const environmentsWarehouseTablesFileCreate = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<environmentsWarehouseTablesFileCreateResponse> => {
    const formData = new FormData()
    if (tableApi.deleted !== undefined && tableApi.deleted !== null) {
        formData.append(`deleted`, tableApi.deleted.toString())
    }
    formData.append(`name`, tableApi.name)
    formData.append(`format`, tableApi.format)
    formData.append(`url_pattern`, tableApi.url_pattern)
    formData.append(`credential`, JSON.stringify(tableApi.credential))

    return apiMutator<environmentsWarehouseTablesFileCreateResponse>(
        getEnvironmentsWarehouseTablesFileCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            body: formData,
        }
    )
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type environmentsWarehouseViewLinkListResponse200 = {
    data: PaginatedViewLinkListApi
    status: 200
}

export type environmentsWarehouseViewLinkListResponseSuccess = environmentsWarehouseViewLinkListResponse200 & {
    headers: Headers
}
export type environmentsWarehouseViewLinkListResponse = environmentsWarehouseViewLinkListResponseSuccess

export const getEnvironmentsWarehouseViewLinkListUrl = (
    projectId: string,
    params?: EnvironmentsWarehouseViewLinkListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/warehouse_view_link/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_view_link/`
}

export const environmentsWarehouseViewLinkList = async (
    projectId: string,
    params?: EnvironmentsWarehouseViewLinkListParams,
    options?: RequestInit
): Promise<environmentsWarehouseViewLinkListResponse> => {
    return apiMutator<environmentsWarehouseViewLinkListResponse>(
        getEnvironmentsWarehouseViewLinkListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type environmentsWarehouseViewLinkCreateResponse201 = {
    data: ViewLinkApi
    status: 201
}

export type environmentsWarehouseViewLinkCreateResponseSuccess = environmentsWarehouseViewLinkCreateResponse201 & {
    headers: Headers
}
export type environmentsWarehouseViewLinkCreateResponse = environmentsWarehouseViewLinkCreateResponseSuccess

export const getEnvironmentsWarehouseViewLinkCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_view_link/`
}

export const environmentsWarehouseViewLinkCreate = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<environmentsWarehouseViewLinkCreateResponse> => {
    return apiMutator<environmentsWarehouseViewLinkCreateResponse>(
        getEnvironmentsWarehouseViewLinkCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(viewLinkApi),
        }
    )
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type environmentsWarehouseViewLinkValidateCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsWarehouseViewLinkValidateCreateResponseSuccess =
    environmentsWarehouseViewLinkValidateCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseViewLinkValidateCreateResponse =
    environmentsWarehouseViewLinkValidateCreateResponseSuccess

export const getEnvironmentsWarehouseViewLinkValidateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_view_link/validate/`
}

export const environmentsWarehouseViewLinkValidateCreate = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<environmentsWarehouseViewLinkValidateCreateResponse> => {
    return apiMutator<environmentsWarehouseViewLinkValidateCreateResponse>(
        getEnvironmentsWarehouseViewLinkValidateCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(viewLinkValidationApi),
        }
    )
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type environmentsWarehouseViewLinksListResponse200 = {
    data: PaginatedViewLinkListApi
    status: 200
}

export type environmentsWarehouseViewLinksListResponseSuccess = environmentsWarehouseViewLinksListResponse200 & {
    headers: Headers
}
export type environmentsWarehouseViewLinksListResponse = environmentsWarehouseViewLinksListResponseSuccess

export const getEnvironmentsWarehouseViewLinksListUrl = (
    projectId: string,
    params?: EnvironmentsWarehouseViewLinksListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/warehouse_view_links/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_view_links/`
}

export const environmentsWarehouseViewLinksList = async (
    projectId: string,
    params?: EnvironmentsWarehouseViewLinksListParams,
    options?: RequestInit
): Promise<environmentsWarehouseViewLinksListResponse> => {
    return apiMutator<environmentsWarehouseViewLinksListResponse>(
        getEnvironmentsWarehouseViewLinksListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type environmentsWarehouseViewLinksCreateResponse201 = {
    data: ViewLinkApi
    status: 201
}

export type environmentsWarehouseViewLinksCreateResponseSuccess = environmentsWarehouseViewLinksCreateResponse201 & {
    headers: Headers
}
export type environmentsWarehouseViewLinksCreateResponse = environmentsWarehouseViewLinksCreateResponseSuccess

export const getEnvironmentsWarehouseViewLinksCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_view_links/`
}

export const environmentsWarehouseViewLinksCreate = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<environmentsWarehouseViewLinksCreateResponse> => {
    return apiMutator<environmentsWarehouseViewLinksCreateResponse>(
        getEnvironmentsWarehouseViewLinksCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(viewLinkApi),
        }
    )
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type environmentsWarehouseViewLinksValidateCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsWarehouseViewLinksValidateCreateResponseSuccess =
    environmentsWarehouseViewLinksValidateCreateResponse200 & {
        headers: Headers
    }
export type environmentsWarehouseViewLinksValidateCreateResponse =
    environmentsWarehouseViewLinksValidateCreateResponseSuccess

export const getEnvironmentsWarehouseViewLinksValidateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_view_links/validate/`
}

export const environmentsWarehouseViewLinksValidateCreate = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<environmentsWarehouseViewLinksValidateCreateResponse> => {
    return apiMutator<environmentsWarehouseViewLinksValidateCreateResponse>(
        getEnvironmentsWarehouseViewLinksValidateCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(viewLinkValidationApi),
        }
    )
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export type dataModelingJobsListResponse200 = {
    data: PaginatedDataModelingJobListApi
    status: 200
}

export type dataModelingJobsListResponseSuccess = dataModelingJobsListResponse200 & {
    headers: Headers
}
export type dataModelingJobsListResponse = dataModelingJobsListResponseSuccess

export const getDataModelingJobsListUrl = (projectId: string, params?: DataModelingJobsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_modeling_jobs/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_jobs/`
}

export const dataModelingJobsList = async (
    projectId: string,
    params?: DataModelingJobsListParams,
    options?: RequestInit
): Promise<dataModelingJobsListResponse> => {
    return apiMutator<dataModelingJobsListResponse>(getDataModelingJobsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export type dataModelingJobsRetrieveResponse200 = {
    data: DataModelingJobApi
    status: 200
}

export type dataModelingJobsRetrieveResponseSuccess = dataModelingJobsRetrieveResponse200 & {
    headers: Headers
}
export type dataModelingJobsRetrieveResponse = dataModelingJobsRetrieveResponseSuccess

export const getDataModelingJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_jobs/${id}/`
}

export const dataModelingJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<dataModelingJobsRetrieveResponse> => {
    return apiMutator<dataModelingJobsRetrieveResponse>(getDataModelingJobsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns completed/non-running activities (jobs with status 'Completed').
Supports pagination and cutoff time filtering.
 */
export type dataWarehouseCompletedActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type dataWarehouseCompletedActivityRetrieveResponseSuccess =
    dataWarehouseCompletedActivityRetrieveResponse200 & {
        headers: Headers
    }
export type dataWarehouseCompletedActivityRetrieveResponse = dataWarehouseCompletedActivityRetrieveResponseSuccess

export const getDataWarehouseCompletedActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/completed_activity/`
}

export const dataWarehouseCompletedActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseCompletedActivityRetrieveResponse> => {
    return apiMutator<dataWarehouseCompletedActivityRetrieveResponse>(
        getDataWarehouseCompletedActivityRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
Includes: materializations, syncs, sources, destinations, and transformations.
 */
export type dataWarehouseDataHealthIssuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type dataWarehouseDataHealthIssuesRetrieveResponseSuccess = dataWarehouseDataHealthIssuesRetrieveResponse200 & {
    headers: Headers
}
export type dataWarehouseDataHealthIssuesRetrieveResponse = dataWarehouseDataHealthIssuesRetrieveResponseSuccess

export const getDataWarehouseDataHealthIssuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/data_health_issues/`
}

export const dataWarehouseDataHealthIssuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseDataHealthIssuesRetrieveResponse> => {
    return apiMutator<dataWarehouseDataHealthIssuesRetrieveResponse>(
        getDataWarehouseDataHealthIssuesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns success and failed job statistics for the last 1, 7, or 30 days.
Query parameter 'days' can be 1, 7, or 30 (default: 7).
 */
export type dataWarehouseJobStatsRetrieveResponse200 = {
    data: void
    status: 200
}

export type dataWarehouseJobStatsRetrieveResponseSuccess = dataWarehouseJobStatsRetrieveResponse200 & {
    headers: Headers
}
export type dataWarehouseJobStatsRetrieveResponse = dataWarehouseJobStatsRetrieveResponseSuccess

export const getDataWarehouseJobStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/job_stats/`
}

export const dataWarehouseJobStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseJobStatsRetrieveResponse> => {
    return apiMutator<dataWarehouseJobStatsRetrieveResponse>(getDataWarehouseJobStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * API endpoints for data warehouse aggregate statistics and operations.
 */
export type dataWarehousePropertyValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type dataWarehousePropertyValuesRetrieveResponseSuccess = dataWarehousePropertyValuesRetrieveResponse200 & {
    headers: Headers
}
export type dataWarehousePropertyValuesRetrieveResponse = dataWarehousePropertyValuesRetrieveResponseSuccess

export const getDataWarehousePropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/property_values/`
}

export const dataWarehousePropertyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehousePropertyValuesRetrieveResponse> => {
    return apiMutator<dataWarehousePropertyValuesRetrieveResponse>(
        getDataWarehousePropertyValuesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns currently running activities (jobs with status 'Running').
Supports pagination and cutoff time filtering.
 */
export type dataWarehouseRunningActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type dataWarehouseRunningActivityRetrieveResponseSuccess = dataWarehouseRunningActivityRetrieveResponse200 & {
    headers: Headers
}
export type dataWarehouseRunningActivityRetrieveResponse = dataWarehouseRunningActivityRetrieveResponseSuccess

export const getDataWarehouseRunningActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/running_activity/`
}

export const dataWarehouseRunningActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseRunningActivityRetrieveResponse> => {
    return apiMutator<dataWarehouseRunningActivityRetrieveResponse>(
        getDataWarehouseRunningActivityRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Returns aggregated statistics for the data warehouse total rows processed within the current billing period.
Used by the frontend data warehouse scene to display usage information.
 */
export type dataWarehouseTotalRowsStatsRetrieveResponse200 = {
    data: void
    status: 200
}

export type dataWarehouseTotalRowsStatsRetrieveResponseSuccess = dataWarehouseTotalRowsStatsRetrieveResponse200 & {
    headers: Headers
}
export type dataWarehouseTotalRowsStatsRetrieveResponse = dataWarehouseTotalRowsStatsRetrieveResponseSuccess

export const getDataWarehouseTotalRowsStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/total_rows_stats/`
}

export const dataWarehouseTotalRowsStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseTotalRowsStatsRetrieveResponse> => {
    return apiMutator<dataWarehouseTotalRowsStatsRetrieveResponse>(
        getDataWarehouseTotalRowsStatsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type externalDataSchemasListResponse200 = {
    data: PaginatedExternalDataSchemaListApi
    status: 200
}

export type externalDataSchemasListResponseSuccess = externalDataSchemasListResponse200 & {
    headers: Headers
}
export type externalDataSchemasListResponse = externalDataSchemasListResponseSuccess

export const getExternalDataSchemasListUrl = (projectId: string, params?: ExternalDataSchemasListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_schemas/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_schemas/`
}

export const externalDataSchemasList = async (
    projectId: string,
    params?: ExternalDataSchemasListParams,
    options?: RequestInit
): Promise<externalDataSchemasListResponse> => {
    return apiMutator<externalDataSchemasListResponse>(getExternalDataSchemasListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type externalDataSchemasCreateResponse201 = {
    data: ExternalDataSchemaApi
    status: 201
}

export type externalDataSchemasCreateResponseSuccess = externalDataSchemasCreateResponse201 & {
    headers: Headers
}
export type externalDataSchemasCreateResponse = externalDataSchemasCreateResponseSuccess

export const getExternalDataSchemasCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_schemas/`
}

export const externalDataSchemasCreate = async (
    projectId: string,
    externalDataSchemaApi: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<externalDataSchemasCreateResponse> => {
    return apiMutator<externalDataSchemasCreateResponse>(getExternalDataSchemasCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesListResponse200 = {
    data: PaginatedExternalDataSourceSerializersListApi
    status: 200
}

export type externalDataSourcesListResponseSuccess = externalDataSourcesListResponse200 & {
    headers: Headers
}
export type externalDataSourcesListResponse = externalDataSourcesListResponseSuccess

export const getExternalDataSourcesListUrl = (projectId: string, params?: ExternalDataSourcesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_sources/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/`
}

export const externalDataSourcesList = async (
    projectId: string,
    params?: ExternalDataSourcesListParams,
    options?: RequestInit
): Promise<externalDataSourcesListResponse> => {
    return apiMutator<externalDataSourcesListResponse>(getExternalDataSourcesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesCreateResponse201 = {
    data: ExternalDataSourceSerializersApi
    status: 201
}

export type externalDataSourcesCreateResponseSuccess = externalDataSourcesCreateResponse201 & {
    headers: Headers
}
export type externalDataSourcesCreateResponse = externalDataSourcesCreateResponseSuccess

export const getExternalDataSourcesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/`
}

export const externalDataSourcesCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesCreateResponse> => {
    return apiMutator<externalDataSourcesCreateResponse>(getExternalDataSourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesRetrieveResponse200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type externalDataSourcesRetrieveResponseSuccess = externalDataSourcesRetrieveResponse200 & {
    headers: Headers
}
export type externalDataSourcesRetrieveResponse = externalDataSourcesRetrieveResponseSuccess

export const getExternalDataSourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<externalDataSourcesRetrieveResponse> => {
    return apiMutator<externalDataSourcesRetrieveResponse>(getExternalDataSourcesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesUpdateResponse200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type externalDataSourcesUpdateResponseSuccess = externalDataSourcesUpdateResponse200 & {
    headers: Headers
}
export type externalDataSourcesUpdateResponse = externalDataSourcesUpdateResponseSuccess

export const getExternalDataSourcesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesUpdate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesUpdateResponse> => {
    return apiMutator<externalDataSourcesUpdateResponse>(getExternalDataSourcesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesPartialUpdateResponse200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type externalDataSourcesPartialUpdateResponseSuccess = externalDataSourcesPartialUpdateResponse200 & {
    headers: Headers
}
export type externalDataSourcesPartialUpdateResponse = externalDataSourcesPartialUpdateResponseSuccess

export const getExternalDataSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesPartialUpdateResponse> => {
    return apiMutator<externalDataSourcesPartialUpdateResponse>(getExternalDataSourcesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesDestroyResponse204 = {
    data: void
    status: 204
}

export type externalDataSourcesDestroyResponseSuccess = externalDataSourcesDestroyResponse204 & {
    headers: Headers
}
export type externalDataSourcesDestroyResponse = externalDataSourcesDestroyResponseSuccess

export const getExternalDataSourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<externalDataSourcesDestroyResponse> => {
    return apiMutator<externalDataSourcesDestroyResponse>(getExternalDataSourcesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesJobsRetrieveResponse200 = {
    data: void
    status: 200
}

export type externalDataSourcesJobsRetrieveResponseSuccess = externalDataSourcesJobsRetrieveResponse200 & {
    headers: Headers
}
export type externalDataSourcesJobsRetrieveResponse = externalDataSourcesJobsRetrieveResponseSuccess

export const getExternalDataSourcesJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/jobs/`
}

export const externalDataSourcesJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<externalDataSourcesJobsRetrieveResponse> => {
    return apiMutator<externalDataSourcesJobsRetrieveResponse>(getExternalDataSourcesJobsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesReloadCreateResponse200 = {
    data: void
    status: 200
}

export type externalDataSourcesReloadCreateResponseSuccess = externalDataSourcesReloadCreateResponse200 & {
    headers: Headers
}
export type externalDataSourcesReloadCreateResponse = externalDataSourcesReloadCreateResponseSuccess

export const getExternalDataSourcesReloadCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/reload/`
}

export const externalDataSourcesReloadCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesReloadCreateResponse> => {
    return apiMutator<externalDataSourcesReloadCreateResponse>(getExternalDataSourcesReloadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export type externalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type externalDataSourcesRevenueAnalyticsConfigPartialUpdateResponseSuccess =
    externalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse200 & {
        headers: Headers
    }
export type externalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse =
    externalDataSourcesRevenueAnalyticsConfigPartialUpdateResponseSuccess

export const getExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/revenue_analytics_config/`
}

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse> => {
    return apiMutator<externalDataSourcesRevenueAnalyticsConfigPartialUpdateResponse>(
        getExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedExternalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesDatabaseSchemaCreateResponse200 = {
    data: void
    status: 200
}

export type externalDataSourcesDatabaseSchemaCreateResponseSuccess =
    externalDataSourcesDatabaseSchemaCreateResponse200 & {
        headers: Headers
    }
export type externalDataSourcesDatabaseSchemaCreateResponse = externalDataSourcesDatabaseSchemaCreateResponseSuccess

export const getExternalDataSourcesDatabaseSchemaCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/database_schema/`
}

export const externalDataSourcesDatabaseSchemaCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesDatabaseSchemaCreateResponse> => {
    return apiMutator<externalDataSourcesDatabaseSchemaCreateResponse>(
        getExternalDataSourcesDatabaseSchemaCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(externalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesSourcePrefixCreateResponse200 = {
    data: void
    status: 200
}

export type externalDataSourcesSourcePrefixCreateResponseSuccess = externalDataSourcesSourcePrefixCreateResponse200 & {
    headers: Headers
}
export type externalDataSourcesSourcePrefixCreateResponse = externalDataSourcesSourcePrefixCreateResponseSuccess

export const getExternalDataSourcesSourcePrefixCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/source_prefix/`
}

export const externalDataSourcesSourcePrefixCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesSourcePrefixCreateResponse> => {
    return apiMutator<externalDataSourcesSourcePrefixCreateResponse>(
        getExternalDataSourcesSourcePrefixCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(externalDataSourceSerializersApi),
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesWizardRetrieveResponse200 = {
    data: void
    status: 200
}

export type externalDataSourcesWizardRetrieveResponseSuccess = externalDataSourcesWizardRetrieveResponse200 & {
    headers: Headers
}
export type externalDataSourcesWizardRetrieveResponse = externalDataSourcesWizardRetrieveResponseSuccess

export const getExternalDataSourcesWizardRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/wizard/`
}

export const externalDataSourcesWizardRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<externalDataSourcesWizardRetrieveResponse> => {
    return apiMutator<externalDataSourcesWizardRetrieveResponse>(getExternalDataSourcesWizardRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export type queryTabStateListResponse200 = {
    data: PaginatedQueryTabStateListApi
    status: 200
}

export type queryTabStateListResponseSuccess = queryTabStateListResponse200 & {
    headers: Headers
}
export type queryTabStateListResponse = queryTabStateListResponseSuccess

export const getQueryTabStateListUrl = (projectId: string, params?: QueryTabStateListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/query_tab_state/?${stringifiedParams}`
        : `/api/projects/${projectId}/query_tab_state/`
}

export const queryTabStateList = async (
    projectId: string,
    params?: QueryTabStateListParams,
    options?: RequestInit
): Promise<queryTabStateListResponse> => {
    return apiMutator<queryTabStateListResponse>(getQueryTabStateListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export type queryTabStateCreateResponse201 = {
    data: QueryTabStateApi
    status: 201
}

export type queryTabStateCreateResponseSuccess = queryTabStateCreateResponse201 & {
    headers: Headers
}
export type queryTabStateCreateResponse = queryTabStateCreateResponseSuccess

export const getQueryTabStateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/query_tab_state/`
}

export const queryTabStateCreate = async (
    projectId: string,
    queryTabStateApi: NonReadonly<QueryTabStateApi>,
    options?: RequestInit
): Promise<queryTabStateCreateResponse> => {
    return apiMutator<queryTabStateCreateResponse>(getQueryTabStateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(queryTabStateApi),
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export type queryTabStateRetrieveResponse200 = {
    data: QueryTabStateApi
    status: 200
}

export type queryTabStateRetrieveResponseSuccess = queryTabStateRetrieveResponse200 & {
    headers: Headers
}
export type queryTabStateRetrieveResponse = queryTabStateRetrieveResponseSuccess

export const getQueryTabStateRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

export const queryTabStateRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<queryTabStateRetrieveResponse> => {
    return apiMutator<queryTabStateRetrieveResponse>(getQueryTabStateRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export type queryTabStateUpdateResponse200 = {
    data: QueryTabStateApi
    status: 200
}

export type queryTabStateUpdateResponseSuccess = queryTabStateUpdateResponse200 & {
    headers: Headers
}
export type queryTabStateUpdateResponse = queryTabStateUpdateResponseSuccess

export const getQueryTabStateUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

export const queryTabStateUpdate = async (
    projectId: string,
    id: string,
    queryTabStateApi: NonReadonly<QueryTabStateApi>,
    options?: RequestInit
): Promise<queryTabStateUpdateResponse> => {
    return apiMutator<queryTabStateUpdateResponse>(getQueryTabStateUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(queryTabStateApi),
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export type queryTabStatePartialUpdateResponse200 = {
    data: QueryTabStateApi
    status: 200
}

export type queryTabStatePartialUpdateResponseSuccess = queryTabStatePartialUpdateResponse200 & {
    headers: Headers
}
export type queryTabStatePartialUpdateResponse = queryTabStatePartialUpdateResponseSuccess

export const getQueryTabStatePartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

export const queryTabStatePartialUpdate = async (
    projectId: string,
    id: string,
    patchedQueryTabStateApi: NonReadonly<PatchedQueryTabStateApi>,
    options?: RequestInit
): Promise<queryTabStatePartialUpdateResponse> => {
    return apiMutator<queryTabStatePartialUpdateResponse>(getQueryTabStatePartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedQueryTabStateApi),
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export type queryTabStateDestroyResponse204 = {
    data: void
    status: 204
}

export type queryTabStateDestroyResponseSuccess = queryTabStateDestroyResponse204 & {
    headers: Headers
}
export type queryTabStateDestroyResponse = queryTabStateDestroyResponseSuccess

export const getQueryTabStateDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

export const queryTabStateDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<queryTabStateDestroyResponse> => {
    return apiMutator<queryTabStateDestroyResponse>(getQueryTabStateDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export type queryTabStateUserRetrieveResponse200 = {
    data: QueryTabStateApi
    status: 200
}

export type queryTabStateUserRetrieveResponseSuccess = queryTabStateUserRetrieveResponse200 & {
    headers: Headers
}
export type queryTabStateUserRetrieveResponse = queryTabStateUserRetrieveResponseSuccess

export const getQueryTabStateUserRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/query_tab_state/user/`
}

export const queryTabStateUserRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<queryTabStateUserRetrieveResponse> => {
    return apiMutator<queryTabStateUserRetrieveResponse>(getQueryTabStateUserRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Return this team's DAG as a set of edges and nodes
 */
export type warehouseDagRetrieveResponse200 = {
    data: void
    status: 200
}

export type warehouseDagRetrieveResponseSuccess = warehouseDagRetrieveResponse200 & {
    headers: Headers
}
export type warehouseDagRetrieveResponse = warehouseDagRetrieveResponseSuccess

export const getWarehouseDagRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_dag/`
}

export const warehouseDagRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<warehouseDagRetrieveResponse> => {
    return apiMutator<warehouseDagRetrieveResponse>(getWarehouseDagRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type warehouseModelPathsListResponse200 = {
    data: PaginatedDataWarehouseModelPathListApi
    status: 200
}

export type warehouseModelPathsListResponseSuccess = warehouseModelPathsListResponse200 & {
    headers: Headers
}
export type warehouseModelPathsListResponse = warehouseModelPathsListResponseSuccess

export const getWarehouseModelPathsListUrl = (projectId: string, params?: WarehouseModelPathsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_model_paths/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_model_paths/`
}

export const warehouseModelPathsList = async (
    projectId: string,
    params?: WarehouseModelPathsListParams,
    options?: RequestInit
): Promise<warehouseModelPathsListResponse> => {
    return apiMutator<warehouseModelPathsListResponse>(getWarehouseModelPathsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesListResponse200 = {
    data: PaginatedDataWarehouseSavedQueryMinimalListApi
    status: 200
}

export type warehouseSavedQueriesListResponseSuccess = warehouseSavedQueriesListResponse200 & {
    headers: Headers
}
export type warehouseSavedQueriesListResponse = warehouseSavedQueriesListResponseSuccess

export const getWarehouseSavedQueriesListUrl = (projectId: string, params?: WarehouseSavedQueriesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_saved_queries/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_saved_queries/`
}

export const warehouseSavedQueriesList = async (
    projectId: string,
    params?: WarehouseSavedQueriesListParams,
    options?: RequestInit
): Promise<warehouseSavedQueriesListResponse> => {
    return apiMutator<warehouseSavedQueriesListResponse>(getWarehouseSavedQueriesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesCreateResponse201 = {
    data: DataWarehouseSavedQueryApi
    status: 201
}

export type warehouseSavedQueriesCreateResponseSuccess = warehouseSavedQueriesCreateResponse201 & {
    headers: Headers
}
export type warehouseSavedQueriesCreateResponse = warehouseSavedQueriesCreateResponseSuccess

export const getWarehouseSavedQueriesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/`
}

export const warehouseSavedQueriesCreate = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesCreateResponse> => {
    return apiMutator<warehouseSavedQueriesCreateResponse>(getWarehouseSavedQueriesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesRetrieveResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesRetrieveResponseSuccess = warehouseSavedQueriesRetrieveResponse200 & {
    headers: Headers
}
export type warehouseSavedQueriesRetrieveResponse = warehouseSavedQueriesRetrieveResponseSuccess

export const getWarehouseSavedQueriesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesRetrieveResponse> => {
    return apiMutator<warehouseSavedQueriesRetrieveResponse>(getWarehouseSavedQueriesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesUpdateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesUpdateResponseSuccess = warehouseSavedQueriesUpdateResponse200 & {
    headers: Headers
}
export type warehouseSavedQueriesUpdateResponse = warehouseSavedQueriesUpdateResponseSuccess

export const getWarehouseSavedQueriesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesUpdateResponse> => {
    return apiMutator<warehouseSavedQueriesUpdateResponse>(getWarehouseSavedQueriesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesPartialUpdateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesPartialUpdateResponseSuccess = warehouseSavedQueriesPartialUpdateResponse200 & {
    headers: Headers
}
export type warehouseSavedQueriesPartialUpdateResponse = warehouseSavedQueriesPartialUpdateResponseSuccess

export const getWarehouseSavedQueriesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryApi: NonReadonly<PatchedDataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesPartialUpdateResponse> => {
    return apiMutator<warehouseSavedQueriesPartialUpdateResponse>(
        getWarehouseSavedQueriesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesDestroyResponse204 = {
    data: void
    status: 204
}

export type warehouseSavedQueriesDestroyResponseSuccess = warehouseSavedQueriesDestroyResponse204 & {
    headers: Headers
}
export type warehouseSavedQueriesDestroyResponse = warehouseSavedQueriesDestroyResponseSuccess

export const getWarehouseSavedQueriesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesDestroyResponse> => {
    return apiMutator<warehouseSavedQueriesDestroyResponse>(getWarehouseSavedQueriesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesActivityRetrieveResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesActivityRetrieveResponseSuccess = warehouseSavedQueriesActivityRetrieveResponse200 & {
    headers: Headers
}
export type warehouseSavedQueriesActivityRetrieveResponse = warehouseSavedQueriesActivityRetrieveResponseSuccess

export const getWarehouseSavedQueriesActivityRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/activity/`
}

export const warehouseSavedQueriesActivityRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesActivityRetrieveResponse> => {
    return apiMutator<warehouseSavedQueriesActivityRetrieveResponse>(
        getWarehouseSavedQueriesActivityRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Return the ancestors of this saved query.

By default, we return the immediate parents. The `level` parameter can be used to
look further back into the ancestor tree. If `level` overshoots (i.e. points to only
ancestors beyond the root), we return an empty list.
 */
export type warehouseSavedQueriesAncestorsCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesAncestorsCreateResponseSuccess = warehouseSavedQueriesAncestorsCreateResponse200 & {
    headers: Headers
}
export type warehouseSavedQueriesAncestorsCreateResponse = warehouseSavedQueriesAncestorsCreateResponseSuccess

export const getWarehouseSavedQueriesAncestorsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/ancestors/`
}

export const warehouseSavedQueriesAncestorsCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesAncestorsCreateResponse> => {
    return apiMutator<warehouseSavedQueriesAncestorsCreateResponse>(
        getWarehouseSavedQueriesAncestorsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Cancel a running saved query workflow.
 */
export type warehouseSavedQueriesCancelCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesCancelCreateResponseSuccess = warehouseSavedQueriesCancelCreateResponse200 & {
    headers: Headers
}
export type warehouseSavedQueriesCancelCreateResponse = warehouseSavedQueriesCancelCreateResponseSuccess

export const getWarehouseSavedQueriesCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/cancel/`
}

export const warehouseSavedQueriesCancelCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesCancelCreateResponse> => {
    return apiMutator<warehouseSavedQueriesCancelCreateResponse>(
        getWarehouseSavedQueriesCancelCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Return the count of immediate upstream and downstream dependencies for this saved query.
 */
export type warehouseSavedQueriesDependenciesRetrieveResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesDependenciesRetrieveResponseSuccess =
    warehouseSavedQueriesDependenciesRetrieveResponse200 & {
        headers: Headers
    }
export type warehouseSavedQueriesDependenciesRetrieveResponse = warehouseSavedQueriesDependenciesRetrieveResponseSuccess

export const getWarehouseSavedQueriesDependenciesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/dependencies/`
}

export const warehouseSavedQueriesDependenciesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesDependenciesRetrieveResponse> => {
    return apiMutator<warehouseSavedQueriesDependenciesRetrieveResponse>(
        getWarehouseSavedQueriesDependenciesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Return the descendants of this saved query.

By default, we return the immediate children. The `level` parameter can be used to
look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
descendants further than a leaf), we return an empty list.
 */
export type warehouseSavedQueriesDescendantsCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesDescendantsCreateResponseSuccess =
    warehouseSavedQueriesDescendantsCreateResponse200 & {
        headers: Headers
    }
export type warehouseSavedQueriesDescendantsCreateResponse = warehouseSavedQueriesDescendantsCreateResponseSuccess

export const getWarehouseSavedQueriesDescendantsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/descendants/`
}

export const warehouseSavedQueriesDescendantsCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesDescendantsCreateResponse> => {
    return apiMutator<warehouseSavedQueriesDescendantsCreateResponse>(
        getWarehouseSavedQueriesDescendantsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export type warehouseSavedQueriesMaterializeCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesMaterializeCreateResponseSuccess =
    warehouseSavedQueriesMaterializeCreateResponse200 & {
        headers: Headers
    }
export type warehouseSavedQueriesMaterializeCreateResponse = warehouseSavedQueriesMaterializeCreateResponseSuccess

export const getWarehouseSavedQueriesMaterializeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/materialize/`
}

export const warehouseSavedQueriesMaterializeCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesMaterializeCreateResponse> => {
    return apiMutator<warehouseSavedQueriesMaterializeCreateResponse>(
        getWarehouseSavedQueriesMaterializeCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Undo materialization, revert back to the original view.
(i.e. delete the materialized table and the schedule)
 */
export type warehouseSavedQueriesRevertMaterializationCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesRevertMaterializationCreateResponseSuccess =
    warehouseSavedQueriesRevertMaterializationCreateResponse200 & {
        headers: Headers
    }
export type warehouseSavedQueriesRevertMaterializationCreateResponse =
    warehouseSavedQueriesRevertMaterializationCreateResponseSuccess

export const getWarehouseSavedQueriesRevertMaterializationCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
}

export const warehouseSavedQueriesRevertMaterializationCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesRevertMaterializationCreateResponse> => {
    return apiMutator<warehouseSavedQueriesRevertMaterializationCreateResponse>(
        getWarehouseSavedQueriesRevertMaterializationCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Run this saved query.
 */
export type warehouseSavedQueriesRunCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesRunCreateResponseSuccess = warehouseSavedQueriesRunCreateResponse200 & {
    headers: Headers
}
export type warehouseSavedQueriesRunCreateResponse = warehouseSavedQueriesRunCreateResponseSuccess

export const getWarehouseSavedQueriesRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run/`
}

export const warehouseSavedQueriesRunCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesRunCreateResponse> => {
    return apiMutator<warehouseSavedQueriesRunCreateResponse>(getWarehouseSavedQueriesRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export type warehouseSavedQueriesRunHistoryRetrieveResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesRunHistoryRetrieveResponseSuccess =
    warehouseSavedQueriesRunHistoryRetrieveResponse200 & {
        headers: Headers
    }
export type warehouseSavedQueriesRunHistoryRetrieveResponse = warehouseSavedQueriesRunHistoryRetrieveResponseSuccess

export const getWarehouseSavedQueriesRunHistoryRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run_history/`
}

export const warehouseSavedQueriesRunHistoryRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesRunHistoryRetrieveResponse> => {
    return apiMutator<warehouseSavedQueriesRunHistoryRetrieveResponse>(
        getWarehouseSavedQueriesRunHistoryRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Resume paused materialization schedules for multiple matviews.

Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
export type warehouseSavedQueriesResumeSchedulesCreateResponse200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesResumeSchedulesCreateResponseSuccess =
    warehouseSavedQueriesResumeSchedulesCreateResponse200 & {
        headers: Headers
    }
export type warehouseSavedQueriesResumeSchedulesCreateResponse =
    warehouseSavedQueriesResumeSchedulesCreateResponseSuccess

export const getWarehouseSavedQueriesResumeSchedulesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/resume_schedules/`
}

export const warehouseSavedQueriesResumeSchedulesCreate = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesResumeSchedulesCreateResponse> => {
    return apiMutator<warehouseSavedQueriesResumeSchedulesCreateResponse>(
        getWarehouseSavedQueriesResumeSchedulesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseTablesListResponse200 = {
    data: PaginatedTableListApi
    status: 200
}

export type warehouseTablesListResponseSuccess = warehouseTablesListResponse200 & {
    headers: Headers
}
export type warehouseTablesListResponse = warehouseTablesListResponseSuccess

export const getWarehouseTablesListUrl = (projectId: string, params?: WarehouseTablesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_tables/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_tables/`
}

export const warehouseTablesList = async (
    projectId: string,
    params?: WarehouseTablesListParams,
    options?: RequestInit
): Promise<warehouseTablesListResponse> => {
    return apiMutator<warehouseTablesListResponse>(getWarehouseTablesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseTablesCreateResponse201 = {
    data: TableApi
    status: 201
}

export type warehouseTablesCreateResponseSuccess = warehouseTablesCreateResponse201 & {
    headers: Headers
}
export type warehouseTablesCreateResponse = warehouseTablesCreateResponseSuccess

export const getWarehouseTablesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/`
}

export const warehouseTablesCreate = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<warehouseTablesCreateResponse> => {
    return apiMutator<warehouseTablesCreateResponse>(getWarehouseTablesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tableApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseTablesFileCreateResponse200 = {
    data: void
    status: 200
}

export type warehouseTablesFileCreateResponseSuccess = warehouseTablesFileCreateResponse200 & {
    headers: Headers
}
export type warehouseTablesFileCreateResponse = warehouseTablesFileCreateResponseSuccess

export const getWarehouseTablesFileCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/file/`
}

export const warehouseTablesFileCreate = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<warehouseTablesFileCreateResponse> => {
    const formData = new FormData()
    if (tableApi.deleted !== undefined && tableApi.deleted !== null) {
        formData.append(`deleted`, tableApi.deleted.toString())
    }
    formData.append(`name`, tableApi.name)
    formData.append(`format`, tableApi.format)
    formData.append(`url_pattern`, tableApi.url_pattern)
    formData.append(`credential`, JSON.stringify(tableApi.credential))

    return apiMutator<warehouseTablesFileCreateResponse>(getWarehouseTablesFileCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinkListResponse200 = {
    data: PaginatedViewLinkListApi
    status: 200
}

export type warehouseViewLinkListResponseSuccess = warehouseViewLinkListResponse200 & {
    headers: Headers
}
export type warehouseViewLinkListResponse = warehouseViewLinkListResponseSuccess

export const getWarehouseViewLinkListUrl = (projectId: string, params?: WarehouseViewLinkListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_view_link/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_view_link/`
}

export const warehouseViewLinkList = async (
    projectId: string,
    params?: WarehouseViewLinkListParams,
    options?: RequestInit
): Promise<warehouseViewLinkListResponse> => {
    return apiMutator<warehouseViewLinkListResponse>(getWarehouseViewLinkListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinkCreateResponse201 = {
    data: ViewLinkApi
    status: 201
}

export type warehouseViewLinkCreateResponseSuccess = warehouseViewLinkCreateResponse201 & {
    headers: Headers
}
export type warehouseViewLinkCreateResponse = warehouseViewLinkCreateResponseSuccess

export const getWarehouseViewLinkCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/`
}

export const warehouseViewLinkCreate = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<warehouseViewLinkCreateResponse> => {
    return apiMutator<warehouseViewLinkCreateResponse>(getWarehouseViewLinkCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinkValidateCreateResponse200 = {
    data: void
    status: 200
}

export type warehouseViewLinkValidateCreateResponseSuccess = warehouseViewLinkValidateCreateResponse200 & {
    headers: Headers
}
export type warehouseViewLinkValidateCreateResponse = warehouseViewLinkValidateCreateResponseSuccess

export const getWarehouseViewLinkValidateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/validate/`
}

export const warehouseViewLinkValidateCreate = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<warehouseViewLinkValidateCreateResponse> => {
    return apiMutator<warehouseViewLinkValidateCreateResponse>(getWarehouseViewLinkValidateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkValidationApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinksListResponse200 = {
    data: PaginatedViewLinkListApi
    status: 200
}

export type warehouseViewLinksListResponseSuccess = warehouseViewLinksListResponse200 & {
    headers: Headers
}
export type warehouseViewLinksListResponse = warehouseViewLinksListResponseSuccess

export const getWarehouseViewLinksListUrl = (projectId: string, params?: WarehouseViewLinksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_view_links/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_view_links/`
}

export const warehouseViewLinksList = async (
    projectId: string,
    params?: WarehouseViewLinksListParams,
    options?: RequestInit
): Promise<warehouseViewLinksListResponse> => {
    return apiMutator<warehouseViewLinksListResponse>(getWarehouseViewLinksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinksCreateResponse201 = {
    data: ViewLinkApi
    status: 201
}

export type warehouseViewLinksCreateResponseSuccess = warehouseViewLinksCreateResponse201 & {
    headers: Headers
}
export type warehouseViewLinksCreateResponse = warehouseViewLinksCreateResponseSuccess

export const getWarehouseViewLinksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/`
}

export const warehouseViewLinksCreate = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<warehouseViewLinksCreateResponse> => {
    return apiMutator<warehouseViewLinksCreateResponse>(getWarehouseViewLinksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinksValidateCreateResponse200 = {
    data: void
    status: 200
}

export type warehouseViewLinksValidateCreateResponseSuccess = warehouseViewLinksValidateCreateResponse200 & {
    headers: Headers
}
export type warehouseViewLinksValidateCreateResponse = warehouseViewLinksValidateCreateResponseSuccess

export const getWarehouseViewLinksValidateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/validate/`
}

export const warehouseViewLinksValidateCreate = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<warehouseViewLinksValidateCreateResponse> => {
    return apiMutator<warehouseViewLinksValidateCreateResponse>(getWarehouseViewLinksValidateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkValidationApi),
    })
}
