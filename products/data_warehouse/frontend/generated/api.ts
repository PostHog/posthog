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
    CheckDatabaseNameResponseApi,
    DataModelingJobApi,
    DataModelingJobsListParams,
    DataWarehouseCheckDatabaseNameRetrieveParams,
    DataWarehouseModelPathApi,
    DataWarehouseSavedQueryApi,
    DataWarehouseSavedQueryColumnAnnotationApi,
    DataWarehouseSavedQueryDraftApi,
    DataWarehouseSavedQueryFolderApi,
    DeleteWarehouseOrgResponseApi,
    DeprovisionWarehouseResponseApi,
    EnableWarehouseBackfillRequestApi,
    EnableWarehouseBackfillResponseApi,
    FixHogqlListParams,
    InsightVariableApi,
    InsightVariablesListParams,
    PaginatedDataModelingJobListApi,
    PaginatedDataWarehouseModelPathListApi,
    PaginatedDataWarehouseSavedQueryColumnAnnotationListApi,
    PaginatedDataWarehouseSavedQueryDraftListApi,
    PaginatedDataWarehouseSavedQueryMinimalListApi,
    PaginatedInsightVariableListApi,
    PaginatedQueryTabStateListApi,
    PaginatedTableListApi,
    PaginatedViewLinkListApi,
    PaginatedWarehouseColumnAnnotationListApi,
    PaginatedWarehouseColumnStatisticsListApi,
    PatchedDataWarehouseSavedQueryApi,
    PatchedDataWarehouseSavedQueryColumnAnnotationApi,
    PatchedDataWarehouseSavedQueryDraftApi,
    PatchedDataWarehouseSavedQueryFolderApi,
    PatchedInsightVariableApi,
    PatchedQueryTabStateApi,
    PatchedTableApi,
    PatchedViewLinkApi,
    PatchedWarehouseColumnAnnotationApi,
    ProvisionWarehouseRequestApi,
    ProvisionWarehouseResponseApi,
    QueryTabStateApi,
    QueryTabStateListParams,
    ResetPasswordResponseApi,
    SavedQueryColumnAnnotationsListParams,
    TableApi,
    ViewLinkApi,
    ViewLinkValidationApi,
    WarehouseColumnAnnotationApi,
    WarehouseColumnAnnotationsListParams,
    WarehouseColumnStatisticsApi,
    WarehouseColumnStatisticsListParams,
    WarehouseModelPathsListParams,
    WarehouseSavedQueriesListParams,
    WarehouseSavedQueryDraftsListParams,
    WarehouseStatusResponseApi,
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

export const getDataModelingJobsListUrl = (projectId: string, params?: DataModelingJobsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_modeling_jobs/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_jobs/`
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
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

export const getDataModelingJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_jobs/${id}/`
}

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
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

export const getDataModelingJobsRecentRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_modeling_jobs/recent/`
}

/**
 * Get the most recent non-running job for each saved query from the v2 backend.
 */
export const dataModelingJobsRecentRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<DataModelingJobApi> => {
    return apiMutator<DataModelingJobApi>(getDataModelingJobsRecentRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingJobsRunningRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_modeling_jobs/running/`
}

/**
 * Get all currently running jobs from the v2 backend.
 */
export const dataModelingJobsRunningRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<DataModelingJobApi> => {
    return apiMutator<DataModelingJobApi>(getDataModelingJobsRunningRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehouseCheckDatabaseNameRetrieveUrl = (
    projectId: string,
    params: DataWarehouseCheckDatabaseNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_warehouse/check-database-name/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_warehouse/check-database-name/`
}

/**
 * Check if a database name is available.
 */
export const dataWarehouseCheckDatabaseNameRetrieve = async (
    projectId: string,
    params: DataWarehouseCheckDatabaseNameRetrieveParams,
    options?: RequestInit
): Promise<CheckDatabaseNameResponseApi> => {
    return apiMutator<CheckDatabaseNameResponseApi>(getDataWarehouseCheckDatabaseNameRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehouseCompletedActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/completed_activity/`
}

/**
 * Returns completed/non-running activities (jobs with status 'Completed').
 * Supports pagination and cutoff time filtering.
 */
export const dataWarehouseCompletedActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataWarehouseCompletedActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehouseDataHealthIssuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/data_health_issues/`
}

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
 * Includes: materializations, syncs, sources, destinations, and transformations.
 */
export const dataWarehouseDataHealthIssuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataWarehouseDataHealthIssuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehouseDataOpsDashboardRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/data_ops_dashboard/`
}

/**
 * Returns the data ops overview dashboard ID for this team, creating it if it doesn't exist yet.
 */
export const dataWarehouseDataOpsDashboardRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDataWarehouseDataOpsDashboardRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehouseDeleteOrgDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/delete-org/`
}

/**
 * Remove the organization's provisioning record after teardown, freeing its warehouse name.
 *
 * Called once the warehouse status reports `deleted`: deprovision tears the warehouse
 * down, this removes the now-empty org row so the database_name can be reused. Restricted
 * to organization admins.
 */
export const dataWarehouseDeleteOrgDestroy = async (
    projectId: string,
    options?: RequestInit
): Promise<DeleteWarehouseOrgResponseApi> => {
    return apiMutator<DeleteWarehouseOrgResponseApi>(getDataWarehouseDeleteOrgDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}

export const getDataWarehouseDeprovisionCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/deprovision/`
}

/**
 * Start deprovisioning the organization's managed warehouse. Restricted to organization admins.
 */
export const dataWarehouseDeprovisionCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<DeprovisionWarehouseResponseApi> => {
    return apiMutator<DeprovisionWarehouseResponseApi>(getDataWarehouseDeprovisionCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getDataWarehouseEnableBackfillCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/enable_backfill/`
}

/**
 * Enable warehouse backfill for this environment with a dedicated set of tables.
 *
 * Requires a table name and records the environment's membership in the
 * organization's managed warehouse. Restricted to organization admins.
 */
export const dataWarehouseEnableBackfillCreate = async (
    projectId: string,
    enableWarehouseBackfillRequestApi: EnableWarehouseBackfillRequestApi,
    options?: RequestInit
): Promise<EnableWarehouseBackfillResponseApi> => {
    return apiMutator<EnableWarehouseBackfillResponseApi>(getDataWarehouseEnableBackfillCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enableWarehouseBackfillRequestApi),
    })
}

export const getDataWarehouseJobStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/job_stats/`
}

/**
 * Returns success and failed job statistics for the last 1, 7, or 30 days.
 * Query parameter 'days' can be 1, 7, or 30 (default: 7).
 */
export const dataWarehouseJobStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseJobStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehousePropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/property_values/`
}

/**
 * API endpoints for data warehouse aggregate statistics and operations.
 */
export const dataWarehousePropertyValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehousePropertyValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehouseProvisionCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/provision/`
}

/**
 * Start provisioning a managed warehouse for this organization (shared by all its teams).
 */
export const dataWarehouseProvisionCreate = async (
    projectId: string,
    provisionWarehouseRequestApi: ProvisionWarehouseRequestApi,
    options?: RequestInit
): Promise<ProvisionWarehouseResponseApi> => {
    return apiMutator<ProvisionWarehouseResponseApi>(getDataWarehouseProvisionCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(provisionWarehouseRequestApi),
    })
}

export const getDataWarehouseResetPasswordCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/reset-password/`
}

/**
 * Reset the root password for the managed warehouse.
 */
export const dataWarehouseResetPasswordCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<ResetPasswordResponseApi> => {
    return apiMutator<ResetPasswordResponseApi>(getDataWarehouseResetPasswordCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getDataWarehouseRunningActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/running_activity/`
}

/**
 * Returns currently running activities (jobs with status 'Running').
 * Supports pagination and cutoff time filtering.
 */
export const dataWarehouseRunningActivityRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseRunningActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehouseTotalRowsStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/total_rows_stats/`
}

/**
 * Returns aggregated statistics for the data warehouse total rows processed within the current billing period.
 * Used by the frontend data warehouse scene to display usage information.
 */
export const dataWarehouseTotalRowsStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataWarehouseTotalRowsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataWarehouseWarehouseStatusRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_warehouse/warehouse_status/`
}

/**
 * Get the current provisioning status of the managed warehouse, with this project's backfill state.
 */
export const dataWarehouseWarehouseStatusRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<WarehouseStatusResponseApi> => {
    return apiMutator<WarehouseStatusResponseApi>(getDataWarehouseWarehouseStatusRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getFixHogqlListUrl = (projectId: string, params?: FixHogqlListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/fix_hogql/?${stringifiedParams}`
        : `/api/projects/${projectId}/fix_hogql/`
}

export const fixHogqlList = async (
    projectId: string,
    params?: FixHogqlListParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFixHogqlListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getFixHogqlCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/fix_hogql/`
}

export const fixHogqlCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFixHogqlCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getFixHogqlRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/fix_hogql/${id}/`
}

export const fixHogqlRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFixHogqlRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFixHogqlUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/fix_hogql/${id}/`
}

export const fixHogqlUpdate = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFixHogqlUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
    })
}

export const getFixHogqlPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/fix_hogql/${id}/`
}

export const fixHogqlPartialUpdate = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFixHogqlPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
    })
}

export const getFixHogqlDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/fix_hogql/${id}/`
}

export const fixHogqlDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFixHogqlDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getInsightVariablesListUrl = (projectId: string, params?: InsightVariablesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/insight_variables/?${stringifiedParams}`
        : `/api/projects/${projectId}/insight_variables/`
}

export const insightVariablesList = async (
    projectId: string,
    params?: InsightVariablesListParams,
    options?: RequestInit
): Promise<PaginatedInsightVariableListApi> => {
    return apiMutator<PaginatedInsightVariableListApi>(getInsightVariablesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getInsightVariablesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/insight_variables/`
}

export const insightVariablesCreate = async (
    projectId: string,
    insightVariableApi: NonReadonly<InsightVariableApi>,
    options?: RequestInit
): Promise<InsightVariableApi> => {
    return apiMutator<InsightVariableApi>(getInsightVariablesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(insightVariableApi),
    })
}

export const getInsightVariablesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/insight_variables/${id}/`
}

export const insightVariablesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<InsightVariableApi> => {
    return apiMutator<InsightVariableApi>(getInsightVariablesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getInsightVariablesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/insight_variables/${id}/`
}

export const insightVariablesUpdate = async (
    projectId: string,
    id: string,
    insightVariableApi: NonReadonly<InsightVariableApi>,
    options?: RequestInit
): Promise<InsightVariableApi> => {
    return apiMutator<InsightVariableApi>(getInsightVariablesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(insightVariableApi),
    })
}

export const getInsightVariablesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/insight_variables/${id}/`
}

export const insightVariablesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedInsightVariableApi?: NonReadonly<PatchedInsightVariableApi>,
    options?: RequestInit
): Promise<InsightVariableApi> => {
    return apiMutator<InsightVariableApi>(getInsightVariablesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedInsightVariableApi),
    })
}

export const getInsightVariablesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/insight_variables/${id}/`
}

export const insightVariablesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getInsightVariablesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getManagedViewsetsRetrieveUrl = (projectId: string, kind: 'revenue_analytics') => {
    return `/api/projects/${projectId}/managed_viewsets/${kind}/`
}

/**
 * Get all views associated with a specific managed viewset.
 * GET /api/environments/{team_id}/managed_viewsets/{kind}/
 */
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

export const getManagedViewsetsUpdateUrl = (projectId: string, kind: 'revenue_analytics') => {
    return `/api/projects/${projectId}/managed_viewsets/${kind}/`
}

/**
 * Enable or disable a managed viewset by kind.
 * PUT /api/environments/{team_id}/managed_viewsets/{kind}/ with body {"enabled": true/false}
 */
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

export const getQueryTabStateListUrl = (projectId: string, params?: QueryTabStateListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/query_tab_state/?${stringifiedParams}`
        : `/api/projects/${projectId}/query_tab_state/`
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
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

export const getQueryTabStateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/query_tab_state/`
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const queryTabStateCreate = async (
    projectId: string,
    queryTabStateApi?: NonReadonly<QueryTabStateApi>,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(queryTabStateApi),
    })
}

export const getQueryTabStateRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
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

export const getQueryTabStateUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const queryTabStateUpdate = async (
    projectId: string,
    id: string,
    queryTabStateApi?: NonReadonly<QueryTabStateApi>,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStateUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(queryTabStateApi),
    })
}

export const getQueryTabStatePartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const queryTabStatePartialUpdate = async (
    projectId: string,
    id: string,
    patchedQueryTabStateApi?: NonReadonly<PatchedQueryTabStateApi>,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStatePartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedQueryTabStateApi),
    })
}

export const getQueryTabStateDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/query_tab_state/${id}/`
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const queryTabStateDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getQueryTabStateDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getQueryTabStateUserRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/query_tab_state/user/`
}

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const queryTabStateUserRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<QueryTabStateApi> => {
    return apiMutator<QueryTabStateApi>(getQueryTabStateUserRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getSavedQueryColumnAnnotationsListUrl = (
    projectId: string,
    params?: SavedQueryColumnAnnotationsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/saved_query_column_annotations/?${stringifiedParams}`
        : `/api/projects/${projectId}/saved_query_column_annotations/`
}

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const savedQueryColumnAnnotationsList = async (
    projectId: string,
    params?: SavedQueryColumnAnnotationsListParams,
    options?: RequestInit
): Promise<PaginatedDataWarehouseSavedQueryColumnAnnotationListApi> => {
    return apiMutator<PaginatedDataWarehouseSavedQueryColumnAnnotationListApi>(
        getSavedQueryColumnAnnotationsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getSavedQueryColumnAnnotationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/saved_query_column_annotations/`
}

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const savedQueryColumnAnnotationsCreate = async (
    projectId: string,
    dataWarehouseSavedQueryColumnAnnotationApi: NonReadonly<DataWarehouseSavedQueryColumnAnnotationApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryColumnAnnotationApi> => {
    return apiMutator<DataWarehouseSavedQueryColumnAnnotationApi>(getSavedQueryColumnAnnotationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryColumnAnnotationApi),
    })
}

export const getSavedQueryColumnAnnotationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/saved_query_column_annotations/${id}/`
}

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const savedQueryColumnAnnotationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryColumnAnnotationApi> => {
    return apiMutator<DataWarehouseSavedQueryColumnAnnotationApi>(
        getSavedQueryColumnAnnotationsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getSavedQueryColumnAnnotationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/saved_query_column_annotations/${id}/`
}

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const savedQueryColumnAnnotationsUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryColumnAnnotationApi: NonReadonly<DataWarehouseSavedQueryColumnAnnotationApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryColumnAnnotationApi> => {
    return apiMutator<DataWarehouseSavedQueryColumnAnnotationApi>(
        getSavedQueryColumnAnnotationsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataWarehouseSavedQueryColumnAnnotationApi),
        }
    )
}

export const getSavedQueryColumnAnnotationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/saved_query_column_annotations/${id}/`
}

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const savedQueryColumnAnnotationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryColumnAnnotationApi?: NonReadonly<PatchedDataWarehouseSavedQueryColumnAnnotationApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryColumnAnnotationApi> => {
    return apiMutator<DataWarehouseSavedQueryColumnAnnotationApi>(
        getSavedQueryColumnAnnotationsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDataWarehouseSavedQueryColumnAnnotationApi),
        }
    )
}

export const getSavedQueryColumnAnnotationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/saved_query_column_annotations/${id}/`
}

/**
 * Read and edit semantic descriptions of data-modelling views and columns surfaced to the AI agent.
 *
 * List can be filtered to one view with `?saved_query_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(saved_query, column_name)`; the view cannot be changed after creation.
 */
export const savedQueryColumnAnnotationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSavedQueryColumnAnnotationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getWarehouseColumnAnnotationsListUrl = (
    projectId: string,
    params?: WarehouseColumnAnnotationsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_column_annotations/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_column_annotations/`
}

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const warehouseColumnAnnotationsList = async (
    projectId: string,
    params?: WarehouseColumnAnnotationsListParams,
    options?: RequestInit
): Promise<PaginatedWarehouseColumnAnnotationListApi> => {
    return apiMutator<PaginatedWarehouseColumnAnnotationListApi>(
        getWarehouseColumnAnnotationsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseColumnAnnotationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_column_annotations/`
}

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const warehouseColumnAnnotationsCreate = async (
    projectId: string,
    warehouseColumnAnnotationApi: NonReadonly<WarehouseColumnAnnotationApi>,
    options?: RequestInit
): Promise<WarehouseColumnAnnotationApi> => {
    return apiMutator<WarehouseColumnAnnotationApi>(getWarehouseColumnAnnotationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(warehouseColumnAnnotationApi),
    })
}

export const getWarehouseColumnAnnotationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_column_annotations/${id}/`
}

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const warehouseColumnAnnotationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<WarehouseColumnAnnotationApi> => {
    return apiMutator<WarehouseColumnAnnotationApi>(getWarehouseColumnAnnotationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseColumnAnnotationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_column_annotations/${id}/`
}

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const warehouseColumnAnnotationsUpdate = async (
    projectId: string,
    id: string,
    warehouseColumnAnnotationApi: NonReadonly<WarehouseColumnAnnotationApi>,
    options?: RequestInit
): Promise<WarehouseColumnAnnotationApi> => {
    return apiMutator<WarehouseColumnAnnotationApi>(getWarehouseColumnAnnotationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(warehouseColumnAnnotationApi),
    })
}

export const getWarehouseColumnAnnotationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_column_annotations/${id}/`
}

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const warehouseColumnAnnotationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedWarehouseColumnAnnotationApi?: NonReadonly<PatchedWarehouseColumnAnnotationApi>,
    options?: RequestInit
): Promise<WarehouseColumnAnnotationApi> => {
    return apiMutator<WarehouseColumnAnnotationApi>(getWarehouseColumnAnnotationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedWarehouseColumnAnnotationApi),
    })
}

export const getWarehouseColumnAnnotationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_column_annotations/${id}/`
}

/**
 * Read and edit semantic descriptions of warehouse tables and columns surfaced to the AI agent.
 *
 * List can be filtered to one table with `?table_id=<uuid>`. Any create or update is treated as a
 * user edit (`is_user_edited=True`), which protects the row from being overwritten by automatic
 * enrichment. Create upserts on `(table, column_name)`; the table cannot be changed after creation.
 */
export const warehouseColumnAnnotationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseColumnAnnotationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getWarehouseColumnStatisticsListUrl = (
    projectId: string,
    params?: WarehouseColumnStatisticsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_column_statistics/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_column_statistics/`
}

/**
 * Read per-column data statistics (null fraction, min/max, row count) for warehouse tables.
 *
 * Statistics are computed automatically after a sync and surfaced to the AI agent so it can write
 * better queries. They are system-owned and read-only here. List can be filtered to one table with
 * `?table_id=<uuid>`.
 */
export const warehouseColumnStatisticsList = async (
    projectId: string,
    params?: WarehouseColumnStatisticsListParams,
    options?: RequestInit
): Promise<PaginatedWarehouseColumnStatisticsListApi> => {
    return apiMutator<PaginatedWarehouseColumnStatisticsListApi>(
        getWarehouseColumnStatisticsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseColumnStatisticsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_column_statistics/${id}/`
}

/**
 * Read per-column data statistics (null fraction, min/max, row count) for warehouse tables.
 *
 * Statistics are computed automatically after a sync and surfaced to the AI agent so it can write
 * better queries. They are system-owned and read-only here. List can be filtered to one table with
 * `?table_id=<uuid>`.
 */
export const warehouseColumnStatisticsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<WarehouseColumnStatisticsApi> => {
    return apiMutator<WarehouseColumnStatisticsApi>(getWarehouseColumnStatisticsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseDagListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_dag/`
}

/**
 * Return this team's DAG as a set of edges and nodes
 */
export const warehouseDagList = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getWarehouseDagListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseModelPathsListUrl = (projectId: string, params?: WarehouseModelPathsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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

export const getWarehouseModelPathsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_model_paths/${id}/`
}

export const warehouseModelPathsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseModelPathApi> => {
    return apiMutator<DataWarehouseModelPathApi>(getWarehouseModelPathsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseSavedQueriesListUrl = (projectId: string, params?: WarehouseSavedQueriesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_saved_queries/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_saved_queries/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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

export const getWarehouseSavedQueriesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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

export const getWarehouseSavedQueriesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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

export const getWarehouseSavedQueriesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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

export const getWarehouseSavedQueriesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseSavedQueriesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryApi?: NonReadonly<PatchedDataWarehouseSavedQueryApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryApi> => {
    return apiMutator<DataWarehouseSavedQueryApi>(getWarehouseSavedQueriesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataWarehouseSavedQueryApi),
    })
}

export const getWarehouseSavedQueriesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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

export const getWarehouseSavedQueriesActivityRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/activity/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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

export const getWarehouseSavedQueriesAncestorsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/ancestors/`
}

/**
 * Return the ancestors of this saved query.
 *
 * By default, we return the immediate parents. The `level` parameter can be used to
 * look further back into the ancestor tree. If `level` overshoots (i.e. points to only
 * ancestors beyond the root), we return an empty list.
 */
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

export const getWarehouseSavedQueriesCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/cancel/`
}

/**
 * Cancel a running saved query workflow.
 */
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

export const getWarehouseSavedQueriesDependenciesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/dependencies/`
}

/**
 * Return the count of immediate upstream and downstream dependencies for this saved query.
 */
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

export const getWarehouseSavedQueriesDescendantsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/descendants/`
}

/**
 * Return the descendants of this saved query.
 *
 * By default, we return the immediate children. The `level` parameter can be used to
 * look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
 * descendants further than a leaf), we return an empty list.
 */
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

export const getWarehouseSavedQueriesMaterializeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/materialize/`
}

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
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

export const getWarehouseSavedQueriesRevertMaterializationCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/revert_materialization/`
}

/**
 * Undo materialization, revert back to the original view.
 * (i.e. delete the materialized table and the schedule)
 */
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

export const getWarehouseSavedQueriesRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run/`
}

/**
 * Run this saved query.
 */
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

export const getWarehouseSavedQueriesRunHistoryRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${id}/run_history/`
}

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
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

export const getWarehouseSavedQueriesResumeSchedulesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/resume_schedules/`
}

/**
 * Resume paused materialization schedules for multiple matviews.
 *
 * Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
 * This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_saved_query_drafts/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_saved_query_drafts/`
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
    return `/api/projects/${projectId}/warehouse_saved_query_drafts/`
}

export const warehouseSavedQueryDraftsCreate = async (
    projectId: string,
    dataWarehouseSavedQueryDraftApi?: NonReadonly<DataWarehouseSavedQueryDraftApi>,
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
    return `/api/projects/${projectId}/warehouse_saved_query_drafts/${id}/`
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
    return `/api/projects/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsUpdate = async (
    projectId: string,
    id: string,
    dataWarehouseSavedQueryDraftApi?: NonReadonly<DataWarehouseSavedQueryDraftApi>,
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
    return `/api/projects/${projectId}/warehouse_saved_query_drafts/${id}/`
}

export const warehouseSavedQueryDraftsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryDraftApi?: NonReadonly<PatchedDataWarehouseSavedQueryDraftApi>,
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
    return `/api/projects/${projectId}/warehouse_saved_query_drafts/${id}/`
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

export const getWarehouseSavedQueryFoldersListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_query_folders/`
}

export const warehouseSavedQueryFoldersList = async (
    projectId: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryFolderApi[]> => {
    return apiMutator<DataWarehouseSavedQueryFolderApi[]>(getWarehouseSavedQueryFoldersListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseSavedQueryFoldersCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_query_folders/`
}

export const warehouseSavedQueryFoldersCreate = async (
    projectId: string,
    dataWarehouseSavedQueryFolderApi: NonReadonly<DataWarehouseSavedQueryFolderApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryFolderApi> => {
    return apiMutator<DataWarehouseSavedQueryFolderApi>(getWarehouseSavedQueryFoldersCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataWarehouseSavedQueryFolderApi),
    })
}

export const getWarehouseSavedQueryFoldersRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_query_folders/${id}/`
}

export const warehouseSavedQueryFoldersRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryFolderApi> => {
    return apiMutator<DataWarehouseSavedQueryFolderApi>(getWarehouseSavedQueryFoldersRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseSavedQueryFoldersPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_query_folders/${id}/`
}

export const warehouseSavedQueryFoldersPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataWarehouseSavedQueryFolderApi?: NonReadonly<PatchedDataWarehouseSavedQueryFolderApi>,
    options?: RequestInit
): Promise<DataWarehouseSavedQueryFolderApi> => {
    return apiMutator<DataWarehouseSavedQueryFolderApi>(getWarehouseSavedQueryFoldersPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataWarehouseSavedQueryFolderApi),
    })
}

export const getWarehouseSavedQueryFoldersDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_query_folders/${id}/`
}

export const warehouseSavedQueryFoldersDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseSavedQueryFoldersDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getWarehouseTablesListUrl = (projectId: string, params?: WarehouseTablesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_tables/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_tables/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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

export const getWarehouseTablesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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

export const getWarehouseTablesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${id}/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TableApi> => {
    return apiMutator<TableApi>(getWarehouseTablesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseTablesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${id}/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesUpdate = async (
    projectId: string,
    id: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<TableApi> => {
    return apiMutator<TableApi>(getWarehouseTablesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tableApi),
    })
}

export const getWarehouseTablesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${id}/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTableApi?: NonReadonly<PatchedTableApi>,
    options?: RequestInit
): Promise<TableApi> => {
    return apiMutator<TableApi>(getWarehouseTablesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTableApi),
    })
}

export const getWarehouseTablesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${id}/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getWarehouseTablesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getWarehouseTablesRefreshSchemaCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${id}/refresh_schema/`
}

/**
 * Re-introspect a self-managed (manually linked) warehouse table's schema from its underlying source files and overwrite its stored column list. Use when the source schema has evolved (e.g. new columns in the underlying Delta/Parquet/CSV files) but queries still can't see the new columns, because PostHog serves a cached column snapshot until the table is refreshed. Not for tables managed by an external data source sync — those refresh on their own schedule.
 * @summary Refresh table schema from source
 */
export const warehouseTablesRefreshSchemaCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseTablesRefreshSchemaCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getWarehouseTablesUpdateSchemaCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${id}/update_schema/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const warehouseTablesUpdateSchemaCreate = async (
    projectId: string,
    id: string,
    tableApi: NonReadonly<TableApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseTablesUpdateSchemaCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tableApi),
    })
}

export const getWarehouseTablesFileCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/file/`
}

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
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
    if (tableApi.options !== undefined) {
        formData.append(`options`, JSON.stringify(tableApi.options))
    }

    return apiMutator<void>(getWarehouseTablesFileCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

export const getWarehouseViewLinkListUrl = (projectId: string, params?: WarehouseViewLinkListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_view_link/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_view_link/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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

export const getWarehouseViewLinkCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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

export const getWarehouseViewLinkRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/${id}/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinkRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseViewLinkUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/${id}/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkUpdate = async (
    projectId: string,
    id: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinkUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

export const getWarehouseViewLinkPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/${id}/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkPartialUpdate = async (
    projectId: string,
    id: string,
    patchedViewLinkApi?: NonReadonly<PatchedViewLinkApi>,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinkPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedViewLinkApi),
    })
}

export const getWarehouseViewLinkDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/${id}/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinkDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getWarehouseViewLinkDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getWarehouseViewLinkValidateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_link/validate/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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

export const getWarehouseViewLinksListUrl = (projectId: string, params?: WarehouseViewLinksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_view_links/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_view_links/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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

export const getWarehouseViewLinksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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

export const getWarehouseViewLinksRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/${id}/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinksRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseViewLinksUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/${id}/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksUpdate = async (
    projectId: string,
    id: string,
    viewLinkApi: NonReadonly<ViewLinkApi>,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinksUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(viewLinkApi),
    })
}

export const getWarehouseViewLinksPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/${id}/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksPartialUpdate = async (
    projectId: string,
    id: string,
    patchedViewLinkApi?: NonReadonly<PatchedViewLinkApi>,
    options?: RequestInit
): Promise<ViewLinkApi> => {
    return apiMutator<ViewLinkApi>(getWarehouseViewLinksPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedViewLinkApi),
    })
}

export const getWarehouseViewLinksDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/${id}/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
export const warehouseViewLinksDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseViewLinksDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getWarehouseViewLinksValidateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_view_links/validate/`
}

/**
 * Create, Read, Update and Delete View Columns.
 */
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
