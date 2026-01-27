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
    DataModelingJobsList2Params,
    DataModelingJobsListParams,
    DataWarehouseSavedQueryApi,
    DataWarehouseSavedQueryDraftApi,
    ExternalDataSchemaApi,
    ExternalDataSchemasList2Params,
    ExternalDataSchemasListParams,
    ExternalDataSourceSerializersApi,
    ExternalDataSourcesList2Params,
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
    WarehouseSavedQueriesList2Params,
    WarehouseSavedQueriesListParams,
    WarehouseSavedQueryDraftsListParams,
    WarehouseTablesList2Params,
    WarehouseTablesListParams,
    WarehouseViewLinkList2Params,
    WarehouseViewLinkListParams,
    WarehouseViewLinksList2Params,
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
        ? `/api/environments/${projectId}/data_modeling_jobs/?${stringifiedParams}`
        : `/api/environments/${projectId}/data_modeling_jobs/`
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
    return `/api/environments/${projectId}/data_modeling_jobs/${id}/`
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
    return `/api/environments/${projectId}/data_warehouse/completed_activity/`
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
    return `/api/environments/${projectId}/data_warehouse/data_health_issues/`
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
    return `/api/environments/${projectId}/data_warehouse/job_stats/`
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
    return `/api/environments/${projectId}/data_warehouse/property_values/`
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
    return `/api/environments/${projectId}/data_warehouse/running_activity/`
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
    return `/api/environments/${projectId}/data_warehouse/total_rows_stats/`
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
        ? `/api/environments/${projectId}/external_data_schemas/?${stringifiedParams}`
        : `/api/environments/${projectId}/external_data_schemas/`
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
    return `/api/environments/${projectId}/external_data_schemas/`
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
        ? `/api/environments/${projectId}/external_data_sources/?${stringifiedParams}`
        : `/api/environments/${projectId}/external_data_sources/`
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
    return `/api/environments/${projectId}/external_data_sources/`
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
    return `/api/environments/${projectId}/external_data_sources/${id}/`
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
    return `/api/environments/${projectId}/external_data_sources/${id}/`
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
    return `/api/environments/${projectId}/external_data_sources/${id}/`
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
    return `/api/environments/${projectId}/external_data_sources/${id}/`
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
    return `/api/environments/${projectId}/external_data_sources/${id}/jobs/`
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
    return `/api/environments/${projectId}/external_data_sources/${id}/reload/`
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
    return `/api/environments/${projectId}/external_data_sources/${id}/revenue_analytics_config/`
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
    return `/api/environments/${projectId}/external_data_sources/database_schema/`
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
    return `/api/environments/${projectId}/external_data_sources/source_prefix/`
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
    return `/api/environments/${projectId}/external_data_sources/wizard/`
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

export type fixHogqlRetrieveResponse200 = {
    data: void
    status: 200
}

export type fixHogqlRetrieveResponseSuccess = fixHogqlRetrieveResponse200 & {
    headers: Headers
}
export type fixHogqlRetrieveResponse = fixHogqlRetrieveResponseSuccess

export const getFixHogqlRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/fix_hogql/`
}

export const fixHogqlRetrieve = async (projectId: string, options?: RequestInit): Promise<fixHogqlRetrieveResponse> => {
    return apiMutator<fixHogqlRetrieveResponse>(getFixHogqlRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type fixHogqlCreateResponse201 = {
    data: void
    status: 201
}

export type fixHogqlCreateResponseSuccess = fixHogqlCreateResponse201 & {
    headers: Headers
}
export type fixHogqlCreateResponse = fixHogqlCreateResponseSuccess

export const getFixHogqlCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/fix_hogql/`
}

export const fixHogqlCreate = async (projectId: string, options?: RequestInit): Promise<fixHogqlCreateResponse> => {
    return apiMutator<fixHogqlCreateResponse>(getFixHogqlCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type lineageGetUpstreamRetrieveResponse200 = {
    data: void
    status: 200
}

export type lineageGetUpstreamRetrieveResponseSuccess = lineageGetUpstreamRetrieveResponse200 & {
    headers: Headers
}
export type lineageGetUpstreamRetrieveResponse = lineageGetUpstreamRetrieveResponseSuccess

export const getLineageGetUpstreamRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/lineage/get_upstream/`
}

export const lineageGetUpstreamRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<lineageGetUpstreamRetrieveResponse> => {
    return apiMutator<lineageGetUpstreamRetrieveResponse>(getLineageGetUpstreamRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get all views associated with a specific managed viewset.
GET /api/environments/{team_id}/managed_viewsets/{kind}/
 */
export type managedViewsetsRetrieveResponse200 = {
    data: void
    status: 200
}

export type managedViewsetsRetrieveResponseSuccess = managedViewsetsRetrieveResponse200 & {
    headers: Headers
}
export type managedViewsetsRetrieveResponse = managedViewsetsRetrieveResponseSuccess

export const getManagedViewsetsRetrieveUrl = (projectId: string, kind: 'revenue_analytics') => {
    return `/api/environments/${projectId}/managed_viewsets/${kind}/`
}

export const managedViewsetsRetrieve = async (
    projectId: string,
    kind: 'revenue_analytics',
    options?: RequestInit
): Promise<managedViewsetsRetrieveResponse> => {
    return apiMutator<managedViewsetsRetrieveResponse>(getManagedViewsetsRetrieveUrl(projectId, kind), {
        ...options,
        method: 'GET',
    })
}

/**
 * Enable or disable a managed viewset by kind.
PUT /api/environments/{team_id}/managed_viewsets/{kind}/ with body {"enabled": true/false}
 */
export type managedViewsetsUpdateResponse200 = {
    data: void
    status: 200
}

export type managedViewsetsUpdateResponseSuccess = managedViewsetsUpdateResponse200 & {
    headers: Headers
}
export type managedViewsetsUpdateResponse = managedViewsetsUpdateResponseSuccess

export const getManagedViewsetsUpdateUrl = (projectId: string, kind: 'revenue_analytics') => {
    return `/api/environments/${projectId}/managed_viewsets/${kind}/`
}

export const managedViewsetsUpdate = async (
    projectId: string,
    kind: 'revenue_analytics',
    options?: RequestInit
): Promise<managedViewsetsUpdateResponse> => {
    return apiMutator<managedViewsetsUpdateResponse>(getManagedViewsetsUpdateUrl(projectId, kind), {
        ...options,
        method: 'PUT',
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
        ? `/api/environments/${projectId}/warehouse_saved_queries/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_saved_queries/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/activity/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/ancestors/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/cancel/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/dependencies/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/descendants/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/materialize/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/run/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/run_history/`
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
    return `/api/environments/${projectId}/warehouse_saved_queries/resume_schedules/`
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

export type warehouseSavedQueryDraftsListResponse200 = {
    data: PaginatedDataWarehouseSavedQueryDraftListApi
    status: 200
}

export type warehouseSavedQueryDraftsListResponseSuccess = warehouseSavedQueryDraftsListResponse200 & {
    headers: Headers
}
export type warehouseSavedQueryDraftsListResponse = warehouseSavedQueryDraftsListResponseSuccess

export const getWarehouseSavedQueryDraftsListUrl = (
    projectId: string,
    params?: WarehouseSavedQueryDraftsListParams
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

export const warehouseSavedQueryDraftsList = async (
    projectId: string,
    params?: WarehouseSavedQueryDraftsListParams,
    options?: RequestInit
): Promise<warehouseSavedQueryDraftsListResponse> => {
    return apiMutator<warehouseSavedQueryDraftsListResponse>(getWarehouseSavedQueryDraftsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type warehouseSavedQueryDraftsCreateResponse201 = {
    data: DataWarehouseSavedQueryDraftApi
    status: 201
}

export type warehouseSavedQueryDraftsCreateResponseSuccess = warehouseSavedQueryDraftsCreateResponse201 & {
    headers: Headers
}
export type warehouseSavedQueryDraftsCreateResponse = warehouseSavedQueryDraftsCreateResponseSuccess

export const getWarehouseSavedQueryDraftsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/`
}

export const warehouseSavedQueryDraftsCreate = async (
    projectId: string,
    dataWarehouseSavedQueryDraftApi: NonReadonly<DataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<warehouseSavedQueryDraftsCreateResponse> => {
    return apiMutator<warehouseSavedQueryDraftsCreateResponse>(getWarehouseSavedQueryDraftsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryDraftApi),
    })
}

export type warehouseSavedQueryDraftsRetrieveResponse200 = {
    data: DataWarehouseSavedQueryDraftApi
    status: 200
}

export type warehouseSavedQueryDraftsRetrieveResponseSuccess = warehouseSavedQueryDraftsRetrieveResponse200 & {
    headers: Headers
}
export type warehouseSavedQueryDraftsRetrieveResponse = warehouseSavedQueryDraftsRetrieveResponseSuccess

export const getWarehouseSavedQueryDraftsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueryDraftsRetrieveResponse> => {
    return apiMutator<warehouseSavedQueryDraftsRetrieveResponse>(
        getWarehouseSavedQueryDraftsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type warehouseSavedQueryDraftsUpdateResponse200 = {
    data: DataWarehouseSavedQueryDraftApi
    status: 200
}

export type warehouseSavedQueryDraftsUpdateResponseSuccess = warehouseSavedQueryDraftsUpdateResponse200 & {
    headers: Headers
}
export type warehouseSavedQueryDraftsUpdateResponse = warehouseSavedQueryDraftsUpdateResponseSuccess

export const getWarehouseSavedQueryDraftsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryDraftApi: NonReadonly<DataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<warehouseSavedQueryDraftsUpdateResponse> => {
    return apiMutator<warehouseSavedQueryDraftsUpdateResponse>(getWarehouseSavedQueryDraftsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryDraftApi),
    })
}

export type warehouseSavedQueryDraftsPartialUpdateResponse200 = {
    data: DataWarehouseSavedQueryDraftApi
    status: 200
}

export type warehouseSavedQueryDraftsPartialUpdateResponseSuccess =
    warehouseSavedQueryDraftsPartialUpdateResponse200 & {
        headers: Headers
    }
export type warehouseSavedQueryDraftsPartialUpdateResponse = warehouseSavedQueryDraftsPartialUpdateResponseSuccess

export const getWarehouseSavedQueryDraftsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryDraftApi: NonReadonly<PatchedDataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<warehouseSavedQueryDraftsPartialUpdateResponse> => {
    return apiMutator<warehouseSavedQueryDraftsPartialUpdateResponse>(
        getWarehouseSavedQueryDraftsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDataWarehouseSavedQueryDraftApi),
        }
    )
}

export type warehouseSavedQueryDraftsDestroyResponse204 = {
    data: void
    status: 204
}

export type warehouseSavedQueryDraftsDestroyResponseSuccess = warehouseSavedQueryDraftsDestroyResponse204 & {
    headers: Headers
}
export type warehouseSavedQueryDraftsDestroyResponse = warehouseSavedQueryDraftsDestroyResponseSuccess

export const getWarehouseSavedQueryDraftsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueryDraftsDestroyResponse> => {
    return apiMutator<warehouseSavedQueryDraftsDestroyResponse>(getWarehouseSavedQueryDraftsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
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
        ? `/api/environments/${projectId}/warehouse_tables/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_tables/`
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
    return `/api/environments/${projectId}/warehouse_tables/`
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
    return `/api/environments/${projectId}/warehouse_tables/file/`
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
        ? `/api/environments/${projectId}/warehouse_view_link/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_view_link/`
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
    return `/api/environments/${projectId}/warehouse_view_link/`
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
    return `/api/environments/${projectId}/warehouse_view_link/validate/`
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
        ? `/api/environments/${projectId}/warehouse_view_links/?${stringifiedParams}`
        : `/api/environments/${projectId}/warehouse_view_links/`
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
    return `/api/environments/${projectId}/warehouse_view_links/`
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
    return `/api/environments/${projectId}/warehouse_view_links/validate/`
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

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export type dataModelingJobsList2Response200 = {
    data: PaginatedDataModelingJobListApi
    status: 200
}

export type dataModelingJobsList2ResponseSuccess = dataModelingJobsList2Response200 & {
    headers: Headers
}
export type dataModelingJobsList2Response = dataModelingJobsList2ResponseSuccess

export const getDataModelingJobsList2Url = (projectId: string, params?: DataModelingJobsList2Params) => {
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

export const dataModelingJobsList2 = async (
    projectId: string,
    params?: DataModelingJobsList2Params,
    options?: RequestInit
): Promise<dataModelingJobsList2Response> => {
    return apiMutator<dataModelingJobsList2Response>(getDataModelingJobsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export type dataModelingJobsRetrieve2Response200 = {
    data: DataModelingJobApi
    status: 200
}

export type dataModelingJobsRetrieve2ResponseSuccess = dataModelingJobsRetrieve2Response200 & {
    headers: Headers
}
export type dataModelingJobsRetrieve2Response = dataModelingJobsRetrieve2ResponseSuccess

export const getDataModelingJobsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_jobs/${id}/`
}

export const dataModelingJobsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<dataModelingJobsRetrieve2Response> => {
    return apiMutator<dataModelingJobsRetrieve2Response>(getDataModelingJobsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns completed/non-running activities (jobs with status 'Completed').
Supports pagination and cutoff time filtering.
 */
export type dataWarehouseCompletedActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type dataWarehouseCompletedActivityRetrieve2ResponseSuccess =
    dataWarehouseCompletedActivityRetrieve2Response200 & {
        headers: Headers
    }
export type dataWarehouseCompletedActivityRetrieve2Response = dataWarehouseCompletedActivityRetrieve2ResponseSuccess

export const getDataWarehouseCompletedActivityRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/completed_activity/`
}

export const dataWarehouseCompletedActivityRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseCompletedActivityRetrieve2Response> => {
    return apiMutator<dataWarehouseCompletedActivityRetrieve2Response>(
        getDataWarehouseCompletedActivityRetrieve2Url(projectId),
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
export type dataWarehouseDataHealthIssuesRetrieve2Response200 = {
    data: void
    status: 200
}

export type dataWarehouseDataHealthIssuesRetrieve2ResponseSuccess =
    dataWarehouseDataHealthIssuesRetrieve2Response200 & {
        headers: Headers
    }
export type dataWarehouseDataHealthIssuesRetrieve2Response = dataWarehouseDataHealthIssuesRetrieve2ResponseSuccess

export const getDataWarehouseDataHealthIssuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/data_health_issues/`
}

export const dataWarehouseDataHealthIssuesRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseDataHealthIssuesRetrieve2Response> => {
    return apiMutator<dataWarehouseDataHealthIssuesRetrieve2Response>(
        getDataWarehouseDataHealthIssuesRetrieve2Url(projectId),
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
export type dataWarehouseJobStatsRetrieve2Response200 = {
    data: void
    status: 200
}

export type dataWarehouseJobStatsRetrieve2ResponseSuccess = dataWarehouseJobStatsRetrieve2Response200 & {
    headers: Headers
}
export type dataWarehouseJobStatsRetrieve2Response = dataWarehouseJobStatsRetrieve2ResponseSuccess

export const getDataWarehouseJobStatsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/job_stats/`
}

export const dataWarehouseJobStatsRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseJobStatsRetrieve2Response> => {
    return apiMutator<dataWarehouseJobStatsRetrieve2Response>(getDataWarehouseJobStatsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * API endpoints for data warehouse aggregate statistics and operations.
 */
export type dataWarehousePropertyValuesRetrieve2Response200 = {
    data: void
    status: 200
}

export type dataWarehousePropertyValuesRetrieve2ResponseSuccess = dataWarehousePropertyValuesRetrieve2Response200 & {
    headers: Headers
}
export type dataWarehousePropertyValuesRetrieve2Response = dataWarehousePropertyValuesRetrieve2ResponseSuccess

export const getDataWarehousePropertyValuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/property_values/`
}

export const dataWarehousePropertyValuesRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehousePropertyValuesRetrieve2Response> => {
    return apiMutator<dataWarehousePropertyValuesRetrieve2Response>(
        getDataWarehousePropertyValuesRetrieve2Url(projectId),
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
export type dataWarehouseRunningActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type dataWarehouseRunningActivityRetrieve2ResponseSuccess = dataWarehouseRunningActivityRetrieve2Response200 & {
    headers: Headers
}
export type dataWarehouseRunningActivityRetrieve2Response = dataWarehouseRunningActivityRetrieve2ResponseSuccess

export const getDataWarehouseRunningActivityRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/running_activity/`
}

export const dataWarehouseRunningActivityRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseRunningActivityRetrieve2Response> => {
    return apiMutator<dataWarehouseRunningActivityRetrieve2Response>(
        getDataWarehouseRunningActivityRetrieve2Url(projectId),
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
export type dataWarehouseTotalRowsStatsRetrieve2Response200 = {
    data: void
    status: 200
}

export type dataWarehouseTotalRowsStatsRetrieve2ResponseSuccess = dataWarehouseTotalRowsStatsRetrieve2Response200 & {
    headers: Headers
}
export type dataWarehouseTotalRowsStatsRetrieve2Response = dataWarehouseTotalRowsStatsRetrieve2ResponseSuccess

export const getDataWarehouseTotalRowsStatsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/total_rows_stats/`
}

export const dataWarehouseTotalRowsStatsRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<dataWarehouseTotalRowsStatsRetrieve2Response> => {
    return apiMutator<dataWarehouseTotalRowsStatsRetrieve2Response>(
        getDataWarehouseTotalRowsStatsRetrieve2Url(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type externalDataSchemasList2Response200 = {
    data: PaginatedExternalDataSchemaListApi
    status: 200
}

export type externalDataSchemasList2ResponseSuccess = externalDataSchemasList2Response200 & {
    headers: Headers
}
export type externalDataSchemasList2Response = externalDataSchemasList2ResponseSuccess

export const getExternalDataSchemasList2Url = (projectId: string, params?: ExternalDataSchemasList2Params) => {
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

export const externalDataSchemasList2 = async (
    projectId: string,
    params?: ExternalDataSchemasList2Params,
    options?: RequestInit
): Promise<externalDataSchemasList2Response> => {
    return apiMutator<externalDataSchemasList2Response>(getExternalDataSchemasList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type externalDataSchemasCreate2Response201 = {
    data: ExternalDataSchemaApi
    status: 201
}

export type externalDataSchemasCreate2ResponseSuccess = externalDataSchemasCreate2Response201 & {
    headers: Headers
}
export type externalDataSchemasCreate2Response = externalDataSchemasCreate2ResponseSuccess

export const getExternalDataSchemasCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_schemas/`
}

export const externalDataSchemasCreate2 = async (
    projectId: string,
    externalDataSchemaApi: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<externalDataSchemasCreate2Response> => {
    return apiMutator<externalDataSchemasCreate2Response>(getExternalDataSchemasCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesList2Response200 = {
    data: PaginatedExternalDataSourceSerializersListApi
    status: 200
}

export type externalDataSourcesList2ResponseSuccess = externalDataSourcesList2Response200 & {
    headers: Headers
}
export type externalDataSourcesList2Response = externalDataSourcesList2ResponseSuccess

export const getExternalDataSourcesList2Url = (projectId: string, params?: ExternalDataSourcesList2Params) => {
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

export const externalDataSourcesList2 = async (
    projectId: string,
    params?: ExternalDataSourcesList2Params,
    options?: RequestInit
): Promise<externalDataSourcesList2Response> => {
    return apiMutator<externalDataSourcesList2Response>(getExternalDataSourcesList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesCreate2Response201 = {
    data: ExternalDataSourceSerializersApi
    status: 201
}

export type externalDataSourcesCreate2ResponseSuccess = externalDataSourcesCreate2Response201 & {
    headers: Headers
}
export type externalDataSourcesCreate2Response = externalDataSourcesCreate2ResponseSuccess

export const getExternalDataSourcesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/`
}

export const externalDataSourcesCreate2 = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesCreate2Response> => {
    return apiMutator<externalDataSourcesCreate2Response>(getExternalDataSourcesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesRetrieve2Response200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type externalDataSourcesRetrieve2ResponseSuccess = externalDataSourcesRetrieve2Response200 & {
    headers: Headers
}
export type externalDataSourcesRetrieve2Response = externalDataSourcesRetrieve2ResponseSuccess

export const getExternalDataSourcesRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<externalDataSourcesRetrieve2Response> => {
    return apiMutator<externalDataSourcesRetrieve2Response>(getExternalDataSourcesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesUpdate2Response200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type externalDataSourcesUpdate2ResponseSuccess = externalDataSourcesUpdate2Response200 & {
    headers: Headers
}
export type externalDataSourcesUpdate2Response = externalDataSourcesUpdate2ResponseSuccess

export const getExternalDataSourcesUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesUpdate2 = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesUpdate2Response> => {
    return apiMutator<externalDataSourcesUpdate2Response>(getExternalDataSourcesUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesPartialUpdate2Response200 = {
    data: ExternalDataSourceSerializersApi
    status: 200
}

export type externalDataSourcesPartialUpdate2ResponseSuccess = externalDataSourcesPartialUpdate2Response200 & {
    headers: Headers
}
export type externalDataSourcesPartialUpdate2Response = externalDataSourcesPartialUpdate2ResponseSuccess

export const getExternalDataSourcesPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesPartialUpdate2Response> => {
    return apiMutator<externalDataSourcesPartialUpdate2Response>(
        getExternalDataSourcesPartialUpdate2Url(projectId, id),
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
export type externalDataSourcesDestroy2Response204 = {
    data: void
    status: 204
}

export type externalDataSourcesDestroy2ResponseSuccess = externalDataSourcesDestroy2Response204 & {
    headers: Headers
}
export type externalDataSourcesDestroy2Response = externalDataSourcesDestroy2ResponseSuccess

export const getExternalDataSourcesDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<externalDataSourcesDestroy2Response> => {
    return apiMutator<externalDataSourcesDestroy2Response>(getExternalDataSourcesDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesJobsRetrieve2Response200 = {
    data: void
    status: 200
}

export type externalDataSourcesJobsRetrieve2ResponseSuccess = externalDataSourcesJobsRetrieve2Response200 & {
    headers: Headers
}
export type externalDataSourcesJobsRetrieve2Response = externalDataSourcesJobsRetrieve2ResponseSuccess

export const getExternalDataSourcesJobsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/jobs/`
}

export const externalDataSourcesJobsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<externalDataSourcesJobsRetrieve2Response> => {
    return apiMutator<externalDataSourcesJobsRetrieve2Response>(getExternalDataSourcesJobsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export type externalDataSourcesReloadCreate2Response200 = {
    data: void
    status: 200
}

export type externalDataSourcesReloadCreate2ResponseSuccess = externalDataSourcesReloadCreate2Response200 & {
    headers: Headers
}
export type externalDataSourcesReloadCreate2Response = externalDataSourcesReloadCreate2ResponseSuccess

export const getExternalDataSourcesReloadCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/reload/`
}

export const externalDataSourcesReloadCreate2 = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesReloadCreate2Response> => {
    return apiMutator<externalDataSourcesReloadCreate2Response>(getExternalDataSourcesReloadCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export type externalDataSourcesRevenueAnalyticsConfigPartialUpdate2Response200 = {
    data: void
    status: 200
}

export type externalDataSourcesRevenueAnalyticsConfigPartialUpdate2ResponseSuccess =
    externalDataSourcesRevenueAnalyticsConfigPartialUpdate2Response200 & {
        headers: Headers
    }
export type externalDataSourcesRevenueAnalyticsConfigPartialUpdate2Response =
    externalDataSourcesRevenueAnalyticsConfigPartialUpdate2ResponseSuccess

export const getExternalDataSourcesRevenueAnalyticsConfigPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/revenue_analytics_config/`
}

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesRevenueAnalyticsConfigPartialUpdate2Response> => {
    return apiMutator<externalDataSourcesRevenueAnalyticsConfigPartialUpdate2Response>(
        getExternalDataSourcesRevenueAnalyticsConfigPartialUpdate2Url(projectId, id),
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
export type externalDataSourcesDatabaseSchemaCreate2Response200 = {
    data: void
    status: 200
}

export type externalDataSourcesDatabaseSchemaCreate2ResponseSuccess =
    externalDataSourcesDatabaseSchemaCreate2Response200 & {
        headers: Headers
    }
export type externalDataSourcesDatabaseSchemaCreate2Response = externalDataSourcesDatabaseSchemaCreate2ResponseSuccess

export const getExternalDataSourcesDatabaseSchemaCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/database_schema/`
}

export const externalDataSourcesDatabaseSchemaCreate2 = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesDatabaseSchemaCreate2Response> => {
    return apiMutator<externalDataSourcesDatabaseSchemaCreate2Response>(
        getExternalDataSourcesDatabaseSchemaCreate2Url(projectId),
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
export type externalDataSourcesSourcePrefixCreate2Response200 = {
    data: void
    status: 200
}

export type externalDataSourcesSourcePrefixCreate2ResponseSuccess =
    externalDataSourcesSourcePrefixCreate2Response200 & {
        headers: Headers
    }
export type externalDataSourcesSourcePrefixCreate2Response = externalDataSourcesSourcePrefixCreate2ResponseSuccess

export const getExternalDataSourcesSourcePrefixCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/source_prefix/`
}

export const externalDataSourcesSourcePrefixCreate2 = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<externalDataSourcesSourcePrefixCreate2Response> => {
    return apiMutator<externalDataSourcesSourcePrefixCreate2Response>(
        getExternalDataSourcesSourcePrefixCreate2Url(projectId),
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
export type externalDataSourcesWizardRetrieve2Response200 = {
    data: void
    status: 200
}

export type externalDataSourcesWizardRetrieve2ResponseSuccess = externalDataSourcesWizardRetrieve2Response200 & {
    headers: Headers
}
export type externalDataSourcesWizardRetrieve2Response = externalDataSourcesWizardRetrieve2ResponseSuccess

export const getExternalDataSourcesWizardRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/wizard/`
}

export const externalDataSourcesWizardRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<externalDataSourcesWizardRetrieve2Response> => {
    return apiMutator<externalDataSourcesWizardRetrieve2Response>(getExternalDataSourcesWizardRetrieve2Url(projectId), {
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
export type warehouseSavedQueriesList2Response200 = {
    data: PaginatedDataWarehouseSavedQueryMinimalListApi
    status: 200
}

export type warehouseSavedQueriesList2ResponseSuccess = warehouseSavedQueriesList2Response200 & {
    headers: Headers
}
export type warehouseSavedQueriesList2Response = warehouseSavedQueriesList2ResponseSuccess

export const getWarehouseSavedQueriesList2Url = (projectId: string, params?: WarehouseSavedQueriesList2Params) => {
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

export const warehouseSavedQueriesList2 = async (
    projectId: string,
    params?: WarehouseSavedQueriesList2Params,
    options?: RequestInit
): Promise<warehouseSavedQueriesList2Response> => {
    return apiMutator<warehouseSavedQueriesList2Response>(getWarehouseSavedQueriesList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesCreate2Response201 = {
    data: DataWarehouseSavedQueryApi
    status: 201
}

export type warehouseSavedQueriesCreate2ResponseSuccess = warehouseSavedQueriesCreate2Response201 & {
    headers: Headers
}
export type warehouseSavedQueriesCreate2Response = warehouseSavedQueriesCreate2ResponseSuccess

export const getWarehouseSavedQueriesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/`
}

export const warehouseSavedQueriesCreate2 = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesCreate2Response> => {
    return apiMutator<warehouseSavedQueriesCreate2Response>(getWarehouseSavedQueriesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesRetrieve2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesRetrieve2ResponseSuccess = warehouseSavedQueriesRetrieve2Response200 & {
    headers: Headers
}
export type warehouseSavedQueriesRetrieve2Response = warehouseSavedQueriesRetrieve2ResponseSuccess

export const getWarehouseSavedQueriesRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesRetrieve2Response> => {
    return apiMutator<warehouseSavedQueriesRetrieve2Response>(getWarehouseSavedQueriesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesUpdate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesUpdate2ResponseSuccess = warehouseSavedQueriesUpdate2Response200 & {
    headers: Headers
}
export type warehouseSavedQueriesUpdate2Response = warehouseSavedQueriesUpdate2ResponseSuccess

export const getWarehouseSavedQueriesUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesUpdate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesUpdate2Response> => {
    return apiMutator<warehouseSavedQueriesUpdate2Response>(getWarehouseSavedQueriesUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesPartialUpdate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesPartialUpdate2ResponseSuccess = warehouseSavedQueriesPartialUpdate2Response200 & {
    headers: Headers
}
export type warehouseSavedQueriesPartialUpdate2Response = warehouseSavedQueriesPartialUpdate2ResponseSuccess

export const getWarehouseSavedQueriesPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryApi: NonReadonly<PatchedDataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesPartialUpdate2Response> => {
    return apiMutator<warehouseSavedQueriesPartialUpdate2Response>(
        getWarehouseSavedQueriesPartialUpdate2Url(projectId, id),
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
export type warehouseSavedQueriesDestroy2Response204 = {
    data: void
    status: 204
}

export type warehouseSavedQueriesDestroy2ResponseSuccess = warehouseSavedQueriesDestroy2Response204 & {
    headers: Headers
}
export type warehouseSavedQueriesDestroy2Response = warehouseSavedQueriesDestroy2ResponseSuccess

export const getWarehouseSavedQueriesDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesDestroy2Response> => {
    return apiMutator<warehouseSavedQueriesDestroy2Response>(getWarehouseSavedQueriesDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseSavedQueriesActivityRetrieve2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesActivityRetrieve2ResponseSuccess =
    warehouseSavedQueriesActivityRetrieve2Response200 & {
        headers: Headers
    }
export type warehouseSavedQueriesActivityRetrieve2Response = warehouseSavedQueriesActivityRetrieve2ResponseSuccess

export const getWarehouseSavedQueriesActivityRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/activity/`
}

export const warehouseSavedQueriesActivityRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesActivityRetrieve2Response> => {
    return apiMutator<warehouseSavedQueriesActivityRetrieve2Response>(
        getWarehouseSavedQueriesActivityRetrieve2Url(projectId, id),
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
export type warehouseSavedQueriesAncestorsCreate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesAncestorsCreate2ResponseSuccess = warehouseSavedQueriesAncestorsCreate2Response200 & {
    headers: Headers
}
export type warehouseSavedQueriesAncestorsCreate2Response = warehouseSavedQueriesAncestorsCreate2ResponseSuccess

export const getWarehouseSavedQueriesAncestorsCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/ancestors/`
}

export const warehouseSavedQueriesAncestorsCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesAncestorsCreate2Response> => {
    return apiMutator<warehouseSavedQueriesAncestorsCreate2Response>(
        getWarehouseSavedQueriesAncestorsCreate2Url(projectId, id),
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
export type warehouseSavedQueriesCancelCreate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesCancelCreate2ResponseSuccess = warehouseSavedQueriesCancelCreate2Response200 & {
    headers: Headers
}
export type warehouseSavedQueriesCancelCreate2Response = warehouseSavedQueriesCancelCreate2ResponseSuccess

export const getWarehouseSavedQueriesCancelCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/cancel/`
}

export const warehouseSavedQueriesCancelCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesCancelCreate2Response> => {
    return apiMutator<warehouseSavedQueriesCancelCreate2Response>(
        getWarehouseSavedQueriesCancelCreate2Url(projectId, id),
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
export type warehouseSavedQueriesDependenciesRetrieve2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesDependenciesRetrieve2ResponseSuccess =
    warehouseSavedQueriesDependenciesRetrieve2Response200 & {
        headers: Headers
    }
export type warehouseSavedQueriesDependenciesRetrieve2Response =
    warehouseSavedQueriesDependenciesRetrieve2ResponseSuccess

export const getWarehouseSavedQueriesDependenciesRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/dependencies/`
}

export const warehouseSavedQueriesDependenciesRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesDependenciesRetrieve2Response> => {
    return apiMutator<warehouseSavedQueriesDependenciesRetrieve2Response>(
        getWarehouseSavedQueriesDependenciesRetrieve2Url(projectId, id),
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
export type warehouseSavedQueriesDescendantsCreate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesDescendantsCreate2ResponseSuccess =
    warehouseSavedQueriesDescendantsCreate2Response200 & {
        headers: Headers
    }
export type warehouseSavedQueriesDescendantsCreate2Response = warehouseSavedQueriesDescendantsCreate2ResponseSuccess

export const getWarehouseSavedQueriesDescendantsCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/descendants/`
}

export const warehouseSavedQueriesDescendantsCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesDescendantsCreate2Response> => {
    return apiMutator<warehouseSavedQueriesDescendantsCreate2Response>(
        getWarehouseSavedQueriesDescendantsCreate2Url(projectId, id),
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
export type warehouseSavedQueriesMaterializeCreate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesMaterializeCreate2ResponseSuccess =
    warehouseSavedQueriesMaterializeCreate2Response200 & {
        headers: Headers
    }
export type warehouseSavedQueriesMaterializeCreate2Response = warehouseSavedQueriesMaterializeCreate2ResponseSuccess

export const getWarehouseSavedQueriesMaterializeCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/materialize/`
}

export const warehouseSavedQueriesMaterializeCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesMaterializeCreate2Response> => {
    return apiMutator<warehouseSavedQueriesMaterializeCreate2Response>(
        getWarehouseSavedQueriesMaterializeCreate2Url(projectId, id),
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
export type warehouseSavedQueriesRevertMaterializationCreate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesRevertMaterializationCreate2ResponseSuccess =
    warehouseSavedQueriesRevertMaterializationCreate2Response200 & {
        headers: Headers
    }
export type warehouseSavedQueriesRevertMaterializationCreate2Response =
    warehouseSavedQueriesRevertMaterializationCreate2ResponseSuccess

export const getWarehouseSavedQueriesRevertMaterializationCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
}

export const warehouseSavedQueriesRevertMaterializationCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesRevertMaterializationCreate2Response> => {
    return apiMutator<warehouseSavedQueriesRevertMaterializationCreate2Response>(
        getWarehouseSavedQueriesRevertMaterializationCreate2Url(projectId, id),
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
export type warehouseSavedQueriesRunCreate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesRunCreate2ResponseSuccess = warehouseSavedQueriesRunCreate2Response200 & {
    headers: Headers
}
export type warehouseSavedQueriesRunCreate2Response = warehouseSavedQueriesRunCreate2ResponseSuccess

export const getWarehouseSavedQueriesRunCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run/`
}

export const warehouseSavedQueriesRunCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesRunCreate2Response> => {
    return apiMutator<warehouseSavedQueriesRunCreate2Response>(getWarehouseSavedQueriesRunCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export type warehouseSavedQueriesRunHistoryRetrieve2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesRunHistoryRetrieve2ResponseSuccess =
    warehouseSavedQueriesRunHistoryRetrieve2Response200 & {
        headers: Headers
    }
export type warehouseSavedQueriesRunHistoryRetrieve2Response = warehouseSavedQueriesRunHistoryRetrieve2ResponseSuccess

export const getWarehouseSavedQueriesRunHistoryRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run_history/`
}

export const warehouseSavedQueriesRunHistoryRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<warehouseSavedQueriesRunHistoryRetrieve2Response> => {
    return apiMutator<warehouseSavedQueriesRunHistoryRetrieve2Response>(
        getWarehouseSavedQueriesRunHistoryRetrieve2Url(projectId, id),
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
export type warehouseSavedQueriesResumeSchedulesCreate2Response200 = {
    data: DataWarehouseSavedQueryApi
    status: 200
}

export type warehouseSavedQueriesResumeSchedulesCreate2ResponseSuccess =
    warehouseSavedQueriesResumeSchedulesCreate2Response200 & {
        headers: Headers
    }
export type warehouseSavedQueriesResumeSchedulesCreate2Response =
    warehouseSavedQueriesResumeSchedulesCreate2ResponseSuccess

export const getWarehouseSavedQueriesResumeSchedulesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/resume_schedules/`
}

export const warehouseSavedQueriesResumeSchedulesCreate2 = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<warehouseSavedQueriesResumeSchedulesCreate2Response> => {
    return apiMutator<warehouseSavedQueriesResumeSchedulesCreate2Response>(
        getWarehouseSavedQueriesResumeSchedulesCreate2Url(projectId),
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
export type warehouseTablesList2Response200 = {
    data: PaginatedTableListApi
    status: 200
}

export type warehouseTablesList2ResponseSuccess = warehouseTablesList2Response200 & {
    headers: Headers
}
export type warehouseTablesList2Response = warehouseTablesList2ResponseSuccess

export const getWarehouseTablesList2Url = (projectId: string, params?: WarehouseTablesList2Params) => {
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

export const warehouseTablesList2 = async (
    projectId: string,
    params?: WarehouseTablesList2Params,
    options?: RequestInit
): Promise<warehouseTablesList2Response> => {
    return apiMutator<warehouseTablesList2Response>(getWarehouseTablesList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseTablesCreate2Response201 = {
    data: TableApi
    status: 201
}

export type warehouseTablesCreate2ResponseSuccess = warehouseTablesCreate2Response201 & {
    headers: Headers
}
export type warehouseTablesCreate2Response = warehouseTablesCreate2ResponseSuccess

export const getWarehouseTablesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/`
}

export const warehouseTablesCreate2 = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<warehouseTablesCreate2Response> => {
    return apiMutator<warehouseTablesCreate2Response>(getWarehouseTablesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tableApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export type warehouseTablesFileCreate2Response200 = {
    data: void
    status: 200
}

export type warehouseTablesFileCreate2ResponseSuccess = warehouseTablesFileCreate2Response200 & {
    headers: Headers
}
export type warehouseTablesFileCreate2Response = warehouseTablesFileCreate2ResponseSuccess

export const getWarehouseTablesFileCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/file/`
}

export const warehouseTablesFileCreate2 = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<warehouseTablesFileCreate2Response> => {
    const formData = new FormData()
    if (tableApi.deleted !== undefined && tableApi.deleted !== null) {
        formData.append(`deleted`, tableApi.deleted.toString())
    }
    formData.append(`name`, tableApi.name)
    formData.append(`format`, tableApi.format)
    formData.append(`url_pattern`, tableApi.url_pattern)
    formData.append(`credential`, JSON.stringify(tableApi.credential))

    return apiMutator<warehouseTablesFileCreate2Response>(getWarehouseTablesFileCreate2Url(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinkList2Response200 = {
    data: PaginatedViewLinkListApi
    status: 200
}

export type warehouseViewLinkList2ResponseSuccess = warehouseViewLinkList2Response200 & {
    headers: Headers
}
export type warehouseViewLinkList2Response = warehouseViewLinkList2ResponseSuccess

export const getWarehouseViewLinkList2Url = (projectId: string, params?: WarehouseViewLinkList2Params) => {
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

export const warehouseViewLinkList2 = async (
    projectId: string,
    params?: WarehouseViewLinkList2Params,
    options?: RequestInit
): Promise<warehouseViewLinkList2Response> => {
    return apiMutator<warehouseViewLinkList2Response>(getWarehouseViewLinkList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinkCreate2Response201 = {
    data: ViewLinkApi
    status: 201
}

export type warehouseViewLinkCreate2ResponseSuccess = warehouseViewLinkCreate2Response201 & {
    headers: Headers
}
export type warehouseViewLinkCreate2Response = warehouseViewLinkCreate2ResponseSuccess

export const getWarehouseViewLinkCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/`
}

export const warehouseViewLinkCreate2 = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<warehouseViewLinkCreate2Response> => {
    return apiMutator<warehouseViewLinkCreate2Response>(getWarehouseViewLinkCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinkValidateCreate2Response200 = {
    data: void
    status: 200
}

export type warehouseViewLinkValidateCreate2ResponseSuccess = warehouseViewLinkValidateCreate2Response200 & {
    headers: Headers
}
export type warehouseViewLinkValidateCreate2Response = warehouseViewLinkValidateCreate2ResponseSuccess

export const getWarehouseViewLinkValidateCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/validate/`
}

export const warehouseViewLinkValidateCreate2 = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<warehouseViewLinkValidateCreate2Response> => {
    return apiMutator<warehouseViewLinkValidateCreate2Response>(getWarehouseViewLinkValidateCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkValidationApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinksList2Response200 = {
    data: PaginatedViewLinkListApi
    status: 200
}

export type warehouseViewLinksList2ResponseSuccess = warehouseViewLinksList2Response200 & {
    headers: Headers
}
export type warehouseViewLinksList2Response = warehouseViewLinksList2ResponseSuccess

export const getWarehouseViewLinksList2Url = (projectId: string, params?: WarehouseViewLinksList2Params) => {
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

export const warehouseViewLinksList2 = async (
    projectId: string,
    params?: WarehouseViewLinksList2Params,
    options?: RequestInit
): Promise<warehouseViewLinksList2Response> => {
    return apiMutator<warehouseViewLinksList2Response>(getWarehouseViewLinksList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinksCreate2Response201 = {
    data: ViewLinkApi
    status: 201
}

export type warehouseViewLinksCreate2ResponseSuccess = warehouseViewLinksCreate2Response201 & {
    headers: Headers
}
export type warehouseViewLinksCreate2Response = warehouseViewLinksCreate2ResponseSuccess

export const getWarehouseViewLinksCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/`
}

export const warehouseViewLinksCreate2 = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<warehouseViewLinksCreate2Response> => {
    return apiMutator<warehouseViewLinksCreate2Response>(getWarehouseViewLinksCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export type warehouseViewLinksValidateCreate2Response200 = {
    data: void
    status: 200
}

export type warehouseViewLinksValidateCreate2ResponseSuccess = warehouseViewLinksValidateCreate2Response200 & {
    headers: Headers
}
export type warehouseViewLinksValidateCreate2Response = warehouseViewLinksValidateCreate2ResponseSuccess

export const getWarehouseViewLinksValidateCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/validate/`
}

export const warehouseViewLinksValidateCreate2 = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<warehouseViewLinksValidateCreate2Response> => {
    return apiMutator<warehouseViewLinksValidateCreate2Response>(getWarehouseViewLinksValidateCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkValidationApi),
    })
}
