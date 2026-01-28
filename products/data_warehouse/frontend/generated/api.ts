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
): Promise<PaginatedDataModelingJobListApi> => {
    return apiMutator<PaginatedDataModelingJobListApi>(getDataModelingJobsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export const getDataModelingJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/data_modeling_jobs/${id}/`
}

export const dataModelingJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataModelingJobApi> => {
    return apiMutator<DataModelingJobApi>(getDataModelingJobsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns completed/non-running activities (jobs with status 'Completed').
Supports pagination and cutoff time filtering.
 */
export const getDataWarehouseCompletedActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/completed_activity/`
}

export const dataWarehouseCompletedActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataWarehouseCompletedActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
Includes: materializations, syncs, sources, destinations, and transformations.
 */
export const getDataWarehouseDataHealthIssuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/data_health_issues/`
}

export const dataWarehouseDataHealthIssuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataWarehouseDataHealthIssuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns success and failed job statistics for the last 1, 7, or 30 days.
Query parameter 'days' can be 1, 7, or 30 (default: 7).
 */
export const getDataWarehouseJobStatsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/job_stats/`
}

export const dataWarehouseJobStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseJobStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * API endpoints for data warehouse aggregate statistics and operations.
 */
export const getDataWarehousePropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/property_values/`
}

export const dataWarehousePropertyValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehousePropertyValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns currently running activities (jobs with status 'Running').
Supports pagination and cutoff time filtering.
 */
export const getDataWarehouseRunningActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/running_activity/`
}

export const dataWarehouseRunningActivityRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseRunningActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns aggregated statistics for the data warehouse total rows processed within the current billing period.
Used by the frontend data warehouse scene to display usage information.
 */
export const getDataWarehouseTotalRowsStatsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/total_rows_stats/`
}

export const dataWarehouseTotalRowsStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseTotalRowsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedExternalDataSchemaListApi> => {
    return apiMutator<PaginatedExternalDataSchemaListApi>(getExternalDataSchemasListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSchemasCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_schemas/`
}

export const externalDataSchemasCreate = async (
    projectId: string,
    externalDataSchemaApi: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<ExternalDataSchemaApi> => {
    return apiMutator<ExternalDataSchemaApi>(getExternalDataSchemasCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
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
): Promise<PaginatedExternalDataSourceSerializersListApi> => {
    return apiMutator<PaginatedExternalDataSourceSerializersListApi>(getExternalDataSourcesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/`
}

export const externalDataSourcesCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesUpdate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/jobs/`
}

export const externalDataSourcesJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesJobsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesReloadCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/reload/`
}

export const externalDataSourcesReloadCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesReloadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const getExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/revenue_analytics_config/`
}

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesDatabaseSchemaCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/database_schema/`
}

export const externalDataSourcesDatabaseSchemaCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesDatabaseSchemaCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesSourcePrefixCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/source_prefix/`
}

export const externalDataSourcesSourcePrefixCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesSourcePrefixCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesWizardRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/wizard/`
}

export const externalDataSourcesWizardRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesWizardRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getFixHogqlRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/fix_hogql/`
}

export const fixHogqlRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFixHogqlRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getFixHogqlCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/fix_hogql/`
}

export const fixHogqlCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFixHogqlCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getLineageGetUpstreamRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/lineage/get_upstream/`
}

export const lineageGetUpstreamRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLineageGetUpstreamRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get all views associated with a specific managed viewset.
GET /api/environments/{team_id}/managed_viewsets/{kind}/
 */
export const getManagedViewsetsRetrieveUrl = (projectId: string, kind: 'revenue_analytics') => {
    return `/api/environments/${projectId}/managed_viewsets/${kind}/`
}

export const managedViewsetsRetrieve = async (
    projectId: string,
    kind: 'revenue_analytics',
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getManagedViewsetsRetrieveUrl(projectId, kind), {
        ...options,
        method: 'GET',
    })
}

/**
 * Enable or disable a managed viewset by kind.
PUT /api/environments/{team_id}/managed_viewsets/{kind}/ with body {"enabled": true/false}
 */
export const getManagedViewsetsUpdateUrl = (projectId: string, kind: 'revenue_analytics') => {
    return `/api/environments/${projectId}/managed_viewsets/${kind}/`
}

export const managedViewsetsUpdate = async (
    projectId: string,
    kind: 'revenue_analytics',
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getManagedViewsetsUpdateUrl(projectId, kind), {
        ...options,
        method: 'PUT',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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
): Promise<PaginatedDataWarehouseSavedQueryMinimalListApi> => {
    return apiMutator<PaginatedDataWarehouseSavedQueryMinimalListApi>(
        getWarehouseSavedQueriesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/`
}

export const warehouseSavedQueriesCreate = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryApi: NonReadonly<PatchedDataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseSavedQueriesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesActivityRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/activity/`
}

export const warehouseSavedQueriesActivityRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesActivityRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Return the ancestors of this saved query.

By default, we return the immediate parents. The `level` parameter can be used to
look further back into the ancestor tree. If `level` overshoots (i.e. points to only
ancestors beyond the root), we return an empty list.
 */
export const getWarehouseSavedQueriesAncestorsCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/ancestors/`
}

export const warehouseSavedQueriesAncestorsCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesAncestorsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Cancel a running saved query workflow.
 */
export const getWarehouseSavedQueriesCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/cancel/`
}

export const warehouseSavedQueriesCancelCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesCancelCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Return the count of immediate upstream and downstream dependencies for this saved query.
 */
export const getWarehouseSavedQueriesDependenciesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/dependencies/`
}

export const warehouseSavedQueriesDependenciesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesDependenciesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Return the descendants of this saved query.

By default, we return the immediate children. The `level` parameter can be used to
look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
descendants further than a leaf), we return an empty list.
 */
export const getWarehouseSavedQueriesDescendantsCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/descendants/`
}

export const warehouseSavedQueriesDescendantsCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesDescendantsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export const getWarehouseSavedQueriesMaterializeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/materialize/`
}

export const warehouseSavedQueriesMaterializeCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesMaterializeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Undo materialization, revert back to the original view.
(i.e. delete the materialized table and the schedule)
 */
export const getWarehouseSavedQueriesRevertMaterializationCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
}

export const warehouseSavedQueriesRevertMaterializationCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getWarehouseSavedQueriesRunCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/run/`
}

export const warehouseSavedQueriesRunCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export const getWarehouseSavedQueriesRunHistoryRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/run_history/`
}

export const warehouseSavedQueriesRunHistoryRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesRunHistoryRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Resume paused materialization schedules for multiple matviews.

Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
export const getWarehouseSavedQueriesResumeSchedulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/resume_schedules/`
}

export const warehouseSavedQueriesResumeSchedulesCreate = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesResumeSchedulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

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
): Promise<PaginatedDataWarehouseSavedQueryDraftListApi> => {
    return apiMutator<PaginatedDataWarehouseSavedQueryDraftListApi>(
        getWarehouseSavedQueryDraftsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseSavedQueryDraftsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/`
}

export const warehouseSavedQueryDraftsCreate = async (
    projectId: string,
    dataWarehouseSavedQueryDraftApi: NonReadonly<DataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryDraftApi> => {
    return apiMutator<DataWarehouseSavedQueryDraftApi>(getWarehouseSavedQueryDraftsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryDraftApi),
    })
}

export const getWarehouseSavedQueryDraftsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryDraftApi> => {
    return apiMutator<DataWarehouseSavedQueryDraftApi>(getWarehouseSavedQueryDraftsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseSavedQueryDraftsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryDraftApi: NonReadonly<DataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryDraftApi> => {
    return apiMutator<DataWarehouseSavedQueryDraftApi>(getWarehouseSavedQueryDraftsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryDraftApi),
    })
}

export const getWarehouseSavedQueryDraftsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryDraftApi: NonReadonly<PatchedDataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryDraftApi> => {
    return apiMutator<DataWarehouseSavedQueryDraftApi>(getWarehouseSavedQueryDraftsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataWarehouseSavedQueryDraftApi),
    })
}

export const getWarehouseSavedQueryDraftsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseSavedQueryDraftsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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
): Promise<PaginatedTableListApi> => {
    return apiMutator<PaginatedTableListApi>(getWarehouseTablesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseTablesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_tables/`
}

export const warehouseTablesCreate = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<TableApi> => {
    return apiMutator<TableApi>(getWarehouseTablesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tableApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseTablesFileCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_tables/file/`
}

export const warehouseTablesFileCreate = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<void> => {
    const formData = new FormData()
    if (tableApi.deleted !== undefined && tableApi.deleted !== null) {
        formData.append(`deleted`, tableApi.deleted.toString())
    }
    formData.append(`name`, tableApi.name)
    formData.append(`format`, tableApi.format)
    formData.append(`url_pattern`, tableApi.url_pattern)
    formData.append(`credential`, JSON.stringify(tableApi.credential))

    return apiMutator<void>(getWarehouseTablesFileCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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
): Promise<PaginatedViewLinkListApi> => {
    return apiMutator<PaginatedViewLinkListApi>(getWarehouseViewLinkListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const getWarehouseViewLinkCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_view_link/`
}

export const warehouseViewLinkCreate = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinkCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const getWarehouseViewLinkValidateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_view_link/validate/`
}

export const warehouseViewLinkValidateCreate = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseViewLinkValidateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkValidationApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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
): Promise<PaginatedViewLinkListApi> => {
    return apiMutator<PaginatedViewLinkListApi>(getWarehouseViewLinksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const getWarehouseViewLinksCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_view_links/`
}

export const warehouseViewLinksCreate = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const getWarehouseViewLinksValidateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_view_links/validate/`
}

export const warehouseViewLinksValidateCreate = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseViewLinksValidateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkValidationApi),
    })
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
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
): Promise<PaginatedDataModelingJobListApi> => {
    return apiMutator<PaginatedDataModelingJobListApi>(getDataModelingJobsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export const getDataModelingJobsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_jobs/${id}/`
}

export const dataModelingJobsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataModelingJobApi> => {
    return apiMutator<DataModelingJobApi>(getDataModelingJobsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns completed/non-running activities (jobs with status 'Completed').
Supports pagination and cutoff time filtering.
 */
export const getDataWarehouseCompletedActivityRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/completed_activity/`
}

export const dataWarehouseCompletedActivityRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataWarehouseCompletedActivityRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
Includes: materializations, syncs, sources, destinations, and transformations.
 */
export const getDataWarehouseDataHealthIssuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/data_health_issues/`
}

export const dataWarehouseDataHealthIssuesRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataWarehouseDataHealthIssuesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns success and failed job statistics for the last 1, 7, or 30 days.
Query parameter 'days' can be 1, 7, or 30 (default: 7).
 */
export const getDataWarehouseJobStatsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/job_stats/`
}

export const dataWarehouseJobStatsRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseJobStatsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * API endpoints for data warehouse aggregate statistics and operations.
 */
export const getDataWarehousePropertyValuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/property_values/`
}

export const dataWarehousePropertyValuesRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehousePropertyValuesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns currently running activities (jobs with status 'Running').
Supports pagination and cutoff time filtering.
 */
export const getDataWarehouseRunningActivityRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/running_activity/`
}

export const dataWarehouseRunningActivityRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataWarehouseRunningActivityRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns aggregated statistics for the data warehouse total rows processed within the current billing period.
Used by the frontend data warehouse scene to display usage information.
 */
export const getDataWarehouseTotalRowsStatsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/total_rows_stats/`
}

export const dataWarehouseTotalRowsStatsRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseTotalRowsStatsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedExternalDataSchemaListApi> => {
    return apiMutator<PaginatedExternalDataSchemaListApi>(getExternalDataSchemasList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSchemasCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_schemas/`
}

export const externalDataSchemasCreate2 = async (
    projectId: string,
    externalDataSchemaApi: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<ExternalDataSchemaApi> => {
    return apiMutator<ExternalDataSchemaApi>(getExternalDataSchemasCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
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
): Promise<PaginatedExternalDataSourceSerializersListApi> => {
    return apiMutator<PaginatedExternalDataSourceSerializersListApi>(
        getExternalDataSourcesList2Url(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/`
}

export const externalDataSourcesCreate2 = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesUpdate2 = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

export const externalDataSourcesDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesJobsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/jobs/`
}

export const externalDataSourcesJobsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesJobsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesReloadCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/reload/`
}

export const externalDataSourcesReloadCreate2 = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesReloadCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const getExternalDataSourcesRevenueAnalyticsConfigPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/revenue_analytics_config/`
}

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesRevenueAnalyticsConfigPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesDatabaseSchemaCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/database_schema/`
}

export const externalDataSourcesDatabaseSchemaCreate2 = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesDatabaseSchemaCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesSourcePrefixCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/source_prefix/`
}

export const externalDataSourcesSourcePrefixCreate2 = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesSourcePrefixCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getExternalDataSourcesWizardRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/wizard/`
}

export const externalDataSourcesWizardRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesWizardRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
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
): Promise<PaginatedQueryTabStateListApi> => {
    return apiMutator<PaginatedQueryTabStateListApi>(getQueryTabStateListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const getQueryTabStateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/query_tab_state/`
}

export const queryTabStateCreate = async (
    projectId: string,
    queryTabStateApi: NonReadonly<QueryTabStateApi>,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(queryTabStateApi),
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const getQueryTabStateRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

export const queryTabStateRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStateRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const getQueryTabStateUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

export const queryTabStateUpdate = async (
    projectId: string,
    id: string,
    queryTabStateApi: NonReadonly<QueryTabStateApi>,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStateUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(queryTabStateApi),
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const getQueryTabStatePartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

export const queryTabStatePartialUpdate = async (
    projectId: string,
    id: string,
    patchedQueryTabStateApi: NonReadonly<PatchedQueryTabStateApi>,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStatePartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedQueryTabStateApi),
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const getQueryTabStateDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

export const queryTabStateDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getQueryTabStateDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const getQueryTabStateUserRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/query_tab_state/user/`
}

export const queryTabStateUserRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStateUserRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Return this team's DAG as a set of edges and nodes
 */
export const getWarehouseDagRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_dag/`
}

export const warehouseDagRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getWarehouseDagRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedDataWarehouseModelPathListApi> => {
    return apiMutator<PaginatedDataWarehouseModelPathListApi>(getWarehouseModelPathsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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
): Promise<PaginatedDataWarehouseSavedQueryMinimalListApi> => {
    return apiMutator<PaginatedDataWarehouseSavedQueryMinimalListApi>(
        getWarehouseSavedQueriesList2Url(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/`
}

export const warehouseSavedQueriesCreate2 = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesUpdate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryApi: NonReadonly<PatchedDataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

export const warehouseSavedQueriesDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseSavedQueriesDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseSavedQueriesActivityRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/activity/`
}

export const warehouseSavedQueriesActivityRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesActivityRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Return the ancestors of this saved query.

By default, we return the immediate parents. The `level` parameter can be used to
look further back into the ancestor tree. If `level` overshoots (i.e. points to only
ancestors beyond the root), we return an empty list.
 */
export const getWarehouseSavedQueriesAncestorsCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/ancestors/`
}

export const warehouseSavedQueriesAncestorsCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesAncestorsCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Cancel a running saved query workflow.
 */
export const getWarehouseSavedQueriesCancelCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/cancel/`
}

export const warehouseSavedQueriesCancelCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesCancelCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Return the count of immediate upstream and downstream dependencies for this saved query.
 */
export const getWarehouseSavedQueriesDependenciesRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/dependencies/`
}

export const warehouseSavedQueriesDependenciesRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesDependenciesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Return the descendants of this saved query.

By default, we return the immediate children. The `level` parameter can be used to
look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
descendants further than a leaf), we return an empty list.
 */
export const getWarehouseSavedQueriesDescendantsCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/descendants/`
}

export const warehouseSavedQueriesDescendantsCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesDescendantsCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export const getWarehouseSavedQueriesMaterializeCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/materialize/`
}

export const warehouseSavedQueriesMaterializeCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesMaterializeCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Undo materialization, revert back to the original view.
(i.e. delete the materialized table and the schedule)
 */
export const getWarehouseSavedQueriesRevertMaterializationCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
}

export const warehouseSavedQueriesRevertMaterializationCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getWarehouseSavedQueriesRunCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run/`
}

export const warehouseSavedQueriesRunCreate2 = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesRunCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export const getWarehouseSavedQueriesRunHistoryRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run_history/`
}

export const warehouseSavedQueriesRunHistoryRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesRunHistoryRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Resume paused materialization schedules for multiple matviews.

Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
export const getWarehouseSavedQueriesResumeSchedulesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/resume_schedules/`
}

export const warehouseSavedQueriesResumeSchedulesCreate2 = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesResumeSchedulesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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
): Promise<PaginatedTableListApi> => {
    return apiMutator<PaginatedTableListApi>(getWarehouseTablesList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseTablesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/`
}

export const warehouseTablesCreate2 = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<TableApi> => {
    return apiMutator<TableApi>(getWarehouseTablesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tableApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getWarehouseTablesFileCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/file/`
}

export const warehouseTablesFileCreate2 = async (
    projectId: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<void> => {
    const formData = new FormData()
    if (tableApi.deleted !== undefined && tableApi.deleted !== null) {
        formData.append(`deleted`, tableApi.deleted.toString())
    }
    formData.append(`name`, tableApi.name)
    formData.append(`format`, tableApi.format)
    formData.append(`url_pattern`, tableApi.url_pattern)
    formData.append(`credential`, JSON.stringify(tableApi.credential))

    return apiMutator<void>(getWarehouseTablesFileCreate2Url(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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
): Promise<PaginatedViewLinkListApi> => {
    return apiMutator<PaginatedViewLinkListApi>(getWarehouseViewLinkList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const getWarehouseViewLinkCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/`
}

export const warehouseViewLinkCreate2 = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinkCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const getWarehouseViewLinkValidateCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/validate/`
}

export const warehouseViewLinkValidateCreate2 = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseViewLinkValidateCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkValidationApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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
): Promise<PaginatedViewLinkListApi> => {
    return apiMutator<PaginatedViewLinkListApi>(getWarehouseViewLinksList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const getWarehouseViewLinksCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/`
}

export const warehouseViewLinksCreate2 = async (
    projectId: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinksCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const getWarehouseViewLinksValidateCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/validate/`
}

export const warehouseViewLinksValidateCreate2 = async (
    projectId: string,
    viewLinkValidationApi: ViewLinkValidationApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseViewLinksValidateCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkValidationApi),
    })
}
