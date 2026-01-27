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
    EnvironmentsExternalDataSourcesListParams,
    EnvironmentsWarehouseSavedQueriesListParams,
    EnvironmentsWarehouseSavedQueryDraftsListParams,
    ExternalDataSourceSerializersApi,
    ExternalDataSourcesListParams,
    PaginatedDataModelingJobListApi,
    PaginatedDataWarehouseSavedQueryDraftListApi,
    PaginatedDataWarehouseSavedQueryMinimalListApi,
    PaginatedExternalDataSourceSerializersListApi,
    PaginatedQueryTabStateListApi,
    PatchedDataWarehouseSavedQueryApi,
    PatchedDataWarehouseSavedQueryDraftApi,
    PatchedExternalDataSourceSerializersApi,
    PatchedQueryTabStateApi,
    QueryTabStateApi,
    QueryTabStateListParams,
    WarehouseSavedQueriesListParams,
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
): Promise<PaginatedDataModelingJobListApi> => {
    return apiMutator<PaginatedDataModelingJobListApi>(getEnvironmentsDataModelingJobsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export const getEnvironmentsDataModelingJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/data_modeling_jobs/${id}/`
}

export const environmentsDataModelingJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataModelingJobApi> => {
    return apiMutator<DataModelingJobApi>(getEnvironmentsDataModelingJobsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns completed/non-running activities (jobs with status 'Completed').
Supports pagination and cutoff time filtering.
 */
export const getEnvironmentsDataWarehouseCompletedActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/completed_activity/`
}

export const environmentsDataWarehouseCompletedActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsDataWarehouseCompletedActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
Includes: materializations, syncs, sources, destinations, and transformations.
 */
export const getEnvironmentsDataWarehouseDataHealthIssuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/data_health_issues/`
}

export const environmentsDataWarehouseDataHealthIssuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsDataWarehouseDataHealthIssuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns success and failed job statistics for the last 1, 7, or 30 days.
Query parameter 'days' can be 1, 7, or 30 (default: 7).
 */
export const getEnvironmentsDataWarehouseJobStatsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/job_stats/`
}

export const environmentsDataWarehouseJobStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsDataWarehouseJobStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * API endpoints for data warehouse aggregate statistics and operations.
 */
export const getEnvironmentsDataWarehousePropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/property_values/`
}

export const environmentsDataWarehousePropertyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsDataWarehousePropertyValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns currently running activities (jobs with status 'Running').
Supports pagination and cutoff time filtering.
 */
export const getEnvironmentsDataWarehouseRunningActivityRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/running_activity/`
}

export const environmentsDataWarehouseRunningActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsDataWarehouseRunningActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Returns aggregated statistics for the data warehouse total rows processed within the current billing period.
Used by the frontend data warehouse scene to display usage information.
 */
export const getEnvironmentsDataWarehouseTotalRowsStatsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_warehouse/total_rows_stats/`
}

export const environmentsDataWarehouseTotalRowsStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsDataWarehouseTotalRowsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
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
): Promise<PaginatedExternalDataSourceSerializersListApi> => {
    return apiMutator<PaginatedExternalDataSourceSerializersListApi>(
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
export const getEnvironmentsExternalDataSourcesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/`
}

export const environmentsExternalDataSourcesCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getEnvironmentsExternalDataSourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getEnvironmentsExternalDataSourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const environmentsExternalDataSourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getEnvironmentsExternalDataSourcesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getEnvironmentsExternalDataSourcesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const environmentsExternalDataSourcesUpdate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getEnvironmentsExternalDataSourcesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getEnvironmentsExternalDataSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const environmentsExternalDataSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(
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
export const getEnvironmentsExternalDataSourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/`
}

export const environmentsExternalDataSourcesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsExternalDataSourcesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getEnvironmentsExternalDataSourcesJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/jobs/`
}

export const environmentsExternalDataSourcesJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsExternalDataSourcesJobsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getEnvironmentsExternalDataSourcesReloadCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/external_data_sources/${id}/reload/`
}

export const environmentsExternalDataSourcesReloadCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsExternalDataSourcesReloadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
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
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getEnvironmentsExternalDataSourcesDatabaseSchemaCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/database_schema/`
}

export const environmentsExternalDataSourcesDatabaseSchemaCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsExternalDataSourcesDatabaseSchemaCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getEnvironmentsExternalDataSourcesSourcePrefixCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/source_prefix/`
}

export const environmentsExternalDataSourcesSourcePrefixCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsExternalDataSourcesSourcePrefixCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const getEnvironmentsExternalDataSourcesWizardRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/external_data_sources/wizard/`
}

export const environmentsExternalDataSourcesWizardRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsExternalDataSourcesWizardRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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
): Promise<PaginatedDataWarehouseSavedQueryMinimalListApi> => {
    return apiMutator<PaginatedDataWarehouseSavedQueryMinimalListApi>(
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
export const getEnvironmentsWarehouseSavedQueriesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/`
}

export const environmentsWarehouseSavedQueriesCreate = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getEnvironmentsWarehouseSavedQueriesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getEnvironmentsWarehouseSavedQueriesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const environmentsWarehouseSavedQueriesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getEnvironmentsWarehouseSavedQueriesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getEnvironmentsWarehouseSavedQueriesUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const environmentsWarehouseSavedQueriesUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getEnvironmentsWarehouseSavedQueriesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getEnvironmentsWarehouseSavedQueriesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const environmentsWarehouseSavedQueriesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryApi: NonReadonly<PatchedDataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getEnvironmentsWarehouseSavedQueriesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataWarehouseSavedQueryApi),
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getEnvironmentsWarehouseSavedQueriesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/`
}

export const environmentsWarehouseSavedQueriesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsWarehouseSavedQueriesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const getEnvironmentsWarehouseSavedQueriesActivityRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/activity/`
}

export const environmentsWarehouseSavedQueriesActivityRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getEnvironmentsWarehouseSavedQueriesAncestorsCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/ancestors/`
}

export const environmentsWarehouseSavedQueriesAncestorsCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getEnvironmentsWarehouseSavedQueriesCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/cancel/`
}

export const environmentsWarehouseSavedQueriesCancelCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getEnvironmentsWarehouseSavedQueriesCancelCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Return the count of immediate upstream and downstream dependencies for this saved query.
 */
export const getEnvironmentsWarehouseSavedQueriesDependenciesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/dependencies/`
}

export const environmentsWarehouseSavedQueriesDependenciesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getEnvironmentsWarehouseSavedQueriesDescendantsCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/descendants/`
}

export const environmentsWarehouseSavedQueriesDescendantsCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getEnvironmentsWarehouseSavedQueriesMaterializeCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/materialize/`
}

export const environmentsWarehouseSavedQueriesMaterializeCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getEnvironmentsWarehouseSavedQueriesRevertMaterializationCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
}

export const environmentsWarehouseSavedQueriesRevertMaterializationCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getEnvironmentsWarehouseSavedQueriesRunCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/run/`
}

export const environmentsWarehouseSavedQueriesRunCreate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getEnvironmentsWarehouseSavedQueriesRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryApi),
    })
}

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export const getEnvironmentsWarehouseSavedQueriesRunHistoryRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/${id}/run_history/`
}

export const environmentsWarehouseSavedQueriesRunHistoryRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
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
export const getEnvironmentsWarehouseSavedQueriesResumeSchedulesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_queries/resume_schedules/`
}

export const environmentsWarehouseSavedQueriesResumeSchedulesCreate = async (
    projectId: string,
    dataWarehouseSavedQueryApi: NonReadonly<DataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(
        getEnvironmentsWarehouseSavedQueriesResumeSchedulesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryApi),
        }
    )
}

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
): Promise<PaginatedDataWarehouseSavedQueryDraftListApi> => {
    return apiMutator<PaginatedDataWarehouseSavedQueryDraftListApi>(
        getEnvironmentsWarehouseSavedQueryDraftsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsWarehouseSavedQueryDraftsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/`
}

export const environmentsWarehouseSavedQueryDraftsCreate = async (
    projectId: string,
    dataWarehouseSavedQueryDraftApi: NonReadonly<DataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryDraftApi> => {
    return apiMutator<DataWarehouseSavedQueryDraftApi>(getEnvironmentsWarehouseSavedQueryDraftsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryDraftApi),
    })
}

export const getEnvironmentsWarehouseSavedQueryDraftsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const environmentsWarehouseSavedQueryDraftsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryDraftApi> => {
    return apiMutator<DataWarehouseSavedQueryDraftApi>(
        getEnvironmentsWarehouseSavedQueryDraftsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsWarehouseSavedQueryDraftsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const environmentsWarehouseSavedQueryDraftsUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryDraftApi: NonReadonly<DataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryDraftApi> => {
    return apiMutator<DataWarehouseSavedQueryDraftApi>(
        getEnvironmentsWarehouseSavedQueryDraftsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryDraftApi),
        }
    )
}

export const getEnvironmentsWarehouseSavedQueryDraftsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const environmentsWarehouseSavedQueryDraftsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryDraftApi: NonReadonly<PatchedDataWarehouseSavedQueryDraftApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryDraftApi> => {
    return apiMutator<DataWarehouseSavedQueryDraftApi>(
        getEnvironmentsWarehouseSavedQueryDraftsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDataWarehouseSavedQueryDraftApi),
        }
    )
}

export const getEnvironmentsWarehouseSavedQueryDraftsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const environmentsWarehouseSavedQueryDraftsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsWarehouseSavedQueryDraftsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
        ? `/api/projects/${projectId}/data_modeling_jobs/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_jobs/`
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
    return `/api/projects/${projectId}/data_modeling_jobs/${id}/`
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
    return `/api/projects/${projectId}/data_warehouse/completed_activity/`
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
    return `/api/projects/${projectId}/data_warehouse/data_health_issues/`
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
    return `/api/projects/${projectId}/data_warehouse/job_stats/`
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
    return `/api/projects/${projectId}/data_warehouse/property_values/`
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
    return `/api/projects/${projectId}/data_warehouse/running_activity/`
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
    return `/api/projects/${projectId}/data_warehouse/total_rows_stats/`
}

export const dataWarehouseTotalRowsStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseTotalRowsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
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
        ? `/api/projects/${projectId}/external_data_sources/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/`
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
    return `/api/projects/${projectId}/external_data_sources/`
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
    return `/api/projects/${projectId}/external_data_sources/${id}/`
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
    return `/api/projects/${projectId}/external_data_sources/${id}/`
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
    return `/api/projects/${projectId}/external_data_sources/${id}/`
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
    return `/api/projects/${projectId}/external_data_sources/${id}/`
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
    return `/api/projects/${projectId}/external_data_sources/${id}/jobs/`
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
    return `/api/projects/${projectId}/external_data_sources/${id}/reload/`
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
    return `/api/projects/${projectId}/external_data_sources/${id}/revenue_analytics_config/`
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
    return `/api/projects/${projectId}/external_data_sources/database_schema/`
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
    return `/api/projects/${projectId}/external_data_sources/source_prefix/`
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
    return `/api/projects/${projectId}/external_data_sources/wizard/`
}

export const externalDataSourcesWizardRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesWizardRetrieveUrl(projectId), {
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
        ? `/api/projects/${projectId}/warehouse_saved_queries/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_saved_queries/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/activity/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/ancestors/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/cancel/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/dependencies/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/descendants/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/materialize/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run_history/`
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
    return `/api/projects/${projectId}/warehouse_saved_queries/resume_schedules/`
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
