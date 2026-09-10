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
    DataQualityCheckApi,
    DataQualityCheckRunApi,
    DataQualityCheckTypeApi,
    DataQualityChecksListParams,
    DataQualityRunRequestApi,
    DataQualityRunsListParams,
    DataQualitySubjectHealthApi,
    DataQualitySuiteRunApi,
    PaginatedDataQualityCheckListApi,
    PaginatedDataQualityOverviewCheckListApi,
    PaginatedDataQualitySuiteRunListApi,
    PatchedDataQualityCheckApi,
    WarehouseSavedQueriesCheckSuiteRunsListParams,
    WarehouseSavedQueriesChecksListParams,
    WarehouseTablesCheckSuiteRunsListParams,
    WarehouseTablesChecksListParams,
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

export const getDataQualityChecksListUrl = (projectId: string, params?: DataQualityChecksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality_checks/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality_checks/`
}

/**
 * Every check in the project, and the health of every subject that has one.
 *
 * The per-subject surfaces answer "what is wrong with this table". This answers "what is wrong
 * across the project", which they cannot: each is nested under one parent. Read-only -- authoring
 * still happens against the subject that owns the check.
 */
export const dataQualityChecksList = async (
    projectId: string,
    params?: DataQualityChecksListParams,
    options?: RequestInit
): Promise<PaginatedDataQualityOverviewCheckListApi> => {
    return apiMutator<PaginatedDataQualityOverviewCheckListApi>(getDataQualityChecksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksHealthListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality_checks/health/`
}

/**
 * Health rollup for every table and view in the project that has checks.
 */
export const dataQualityChecksHealthList = async (
    projectId: string,
    options?: RequestInit
): Promise<DataQualitySubjectHealthApi[]> => {
    return apiMutator<DataQualitySubjectHealthApi[]>(getDataQualityChecksHealthListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityRunsListUrl = (projectId: string, params?: DataQualityRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality_runs/`
}

/**
 * Project-wide check runs: start one over a selection, and read every run the project has had.
 *
 * The per-subject surfaces only serve runs scoped to their own subject, so this is where a sweep
 * across several subjects -- a manual project-wide run, a materialization, a source sync -- is
 * readable. Scoped to `warehouse_objects` because it spans tables and views at once.
 */
export const dataQualityRunsList = async (
    projectId: string,
    params?: DataQualityRunsListParams,
    options?: RequestInit
): Promise<PaginatedDataQualitySuiteRunListApi> => {
    return apiMutator<PaginatedDataQualitySuiteRunListApi>(getDataQualityRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityRunsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality_runs/`
}

/**
 * Run the named checks now, or every enabled check in the project when none are named. Returns the suite run to poll for the report.
 */
export const dataQualityRunsCreate = async (
    projectId: string,
    dataQualityRunRequestApi?: DataQualityRunRequestApi,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getDataQualityRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityRunRequestApi),
    })
}

export const getDataQualityRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality_runs/${id}/`
}

/**
 * Project-wide check runs: start one over a selection, and read every run the project has had.
 *
 * The per-subject surfaces only serve runs scoped to their own subject, so this is where a sweep
 * across several subjects -- a manual project-wide run, a materialization, a source sync -- is
 * readable. Scoped to `warehouse_objects` because it spans tables and views at once.
 */
export const dataQualityRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getDataQualityRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseSavedQueriesCheckSuiteRunsListUrl = (
    projectId: string,
    savedQueryId: string,
    params?: WarehouseSavedQueriesCheckSuiteRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/check_suite_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/check_suite_runs/`
}

/**
 * Read-only reports for this subject's check-suite executions.
 */
export const warehouseSavedQueriesCheckSuiteRunsList = async (
    projectId: string,
    savedQueryId: string,
    params?: WarehouseSavedQueriesCheckSuiteRunsListParams,
    options?: RequestInit
): Promise<PaginatedDataQualitySuiteRunListApi> => {
    return apiMutator<PaginatedDataQualitySuiteRunListApi>(
        getWarehouseSavedQueriesCheckSuiteRunsListUrl(projectId, savedQueryId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseSavedQueriesCheckSuiteRunsRetrieveUrl = (
    projectId: string,
    savedQueryId: string,
    id: string
) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/check_suite_runs/${id}/`
}

/**
 * Read-only reports for this subject's check-suite executions.
 */
export const warehouseSavedQueriesCheckSuiteRunsRetrieve = async (
    projectId: string,
    savedQueryId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(
        getWarehouseSavedQueriesCheckSuiteRunsRetrieveUrl(projectId, savedQueryId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseSavedQueriesCheckSuiteRunsCheckRunsListUrl = (
    projectId: string,
    savedQueryId: string,
    id: string
) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/check_suite_runs/${id}/check_runs/`
}

/**
 * Every check execution in this suite run.
 */
export const warehouseSavedQueriesCheckSuiteRunsCheckRunsList = async (
    projectId: string,
    savedQueryId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckRunApi[]> => {
    return apiMutator<DataQualityCheckRunApi[]>(
        getWarehouseSavedQueriesCheckSuiteRunsCheckRunsListUrl(projectId, savedQueryId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseSavedQueriesChecksListUrl = (
    projectId: string,
    savedQueryId: string,
    params?: WarehouseSavedQueriesChecksListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/`
}

/**
 * CRUD for one subject's checks, plus the actions that run them and report on them.
 */
export const warehouseSavedQueriesChecksList = async (
    projectId: string,
    savedQueryId: string,
    params?: WarehouseSavedQueriesChecksListParams,
    options?: RequestInit
): Promise<PaginatedDataQualityCheckListApi> => {
    return apiMutator<PaginatedDataQualityCheckListApi>(
        getWarehouseSavedQueriesChecksListUrl(projectId, savedQueryId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseSavedQueriesChecksCreateUrl = (projectId: string, savedQueryId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/`
}

/**
 * Create a check on this table or view, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const warehouseSavedQueriesChecksCreate = async (
    projectId: string,
    savedQueryId: string,
    dataQualityCheckApi: NonReadonly<DataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getWarehouseSavedQueriesChecksCreateUrl(projectId, savedQueryId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityCheckApi),
    })
}

export const getWarehouseSavedQueriesChecksRetrieveUrl = (projectId: string, savedQueryId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/${id}/`
}

/**
 * CRUD for one subject's checks, plus the actions that run them and report on them.
 */
export const warehouseSavedQueriesChecksRetrieve = async (
    projectId: string,
    savedQueryId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getWarehouseSavedQueriesChecksRetrieveUrl(projectId, savedQueryId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseSavedQueriesChecksUpdateUrl = (projectId: string, savedQueryId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/${id}/`
}

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const warehouseSavedQueriesChecksUpdate = async (
    projectId: string,
    savedQueryId: string,
    id: string,
    dataQualityCheckApi: NonReadonly<DataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getWarehouseSavedQueriesChecksUpdateUrl(projectId, savedQueryId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityCheckApi),
    })
}

export const getWarehouseSavedQueriesChecksPartialUpdateUrl = (projectId: string, savedQueryId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/${id}/`
}

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const warehouseSavedQueriesChecksPartialUpdate = async (
    projectId: string,
    savedQueryId: string,
    id: string,
    patchedDataQualityCheckApi?: NonReadonly<PatchedDataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(
        getWarehouseSavedQueriesChecksPartialUpdateUrl(projectId, savedQueryId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDataQualityCheckApi),
        }
    )
}

export const getWarehouseSavedQueriesChecksDestroyUrl = (projectId: string, savedQueryId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/${id}/`
}

/**
 * CRUD for one subject's checks, plus the actions that run them and report on them.
 */
export const warehouseSavedQueriesChecksDestroy = async (
    projectId: string,
    savedQueryId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseSavedQueriesChecksDestroyUrl(projectId, savedQueryId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getWarehouseSavedQueriesChecksRunCreateUrl = (projectId: string, savedQueryId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/${id}/run/`
}

/**
 * Run this check now. Returns the suite run to poll for the report.
 */
export const warehouseSavedQueriesChecksRunCreate = async (
    projectId: string,
    savedQueryId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getWarehouseSavedQueriesChecksRunCreateUrl(projectId, savedQueryId, id), {
        ...options,
        method: 'POST',
    })
}

export const getWarehouseSavedQueriesChecksRunsListUrl = (projectId: string, savedQueryId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/${id}/runs/`
}

/**
 * Recent run history for this check, newest first.
 */
export const warehouseSavedQueriesChecksRunsList = async (
    projectId: string,
    savedQueryId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckRunApi[]> => {
    return apiMutator<DataQualityCheckRunApi[]>(
        getWarehouseSavedQueriesChecksRunsListUrl(projectId, savedQueryId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseSavedQueriesChecksCheckTypesListUrl = (projectId: string, savedQueryId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/check_types/`
}

/**
 * The check types this project can author, with the JSON schema of each type's config.
 */
export const warehouseSavedQueriesChecksCheckTypesList = async (
    projectId: string,
    savedQueryId: string,
    options?: RequestInit
): Promise<DataQualityCheckTypeApi[]> => {
    return apiMutator<DataQualityCheckTypeApi[]>(
        getWarehouseSavedQueriesChecksCheckTypesListUrl(projectId, savedQueryId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseSavedQueriesChecksHealthRetrieveUrl = (projectId: string, savedQueryId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/health/`
}

/**
 * Health rollup for this table or view, from the denormalized status of its checks.
 */
export const warehouseSavedQueriesChecksHealthRetrieve = async (
    projectId: string,
    savedQueryId: string,
    options?: RequestInit
): Promise<DataQualitySubjectHealthApi> => {
    return apiMutator<DataQualitySubjectHealthApi>(
        getWarehouseSavedQueriesChecksHealthRetrieveUrl(projectId, savedQueryId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseSavedQueriesChecksRunAllCreateUrl = (projectId: string, savedQueryId: string) => {
    return `/api/projects/${projectId}/warehouse_saved_queries/${savedQueryId}/checks/run_all/`
}

/**
 * Run every enabled check on this table or view. Returns the suite run to poll.
 */
export const warehouseSavedQueriesChecksRunAllCreate = async (
    projectId: string,
    savedQueryId: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getWarehouseSavedQueriesChecksRunAllCreateUrl(projectId, savedQueryId), {
        ...options,
        method: 'POST',
    })
}

export const getWarehouseTablesCheckSuiteRunsListUrl = (
    projectId: string,
    tableId: string,
    params?: WarehouseTablesCheckSuiteRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_tables/${tableId}/check_suite_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_tables/${tableId}/check_suite_runs/`
}

/**
 * Read-only reports for this subject's check-suite executions.
 */
export const warehouseTablesCheckSuiteRunsList = async (
    projectId: string,
    tableId: string,
    params?: WarehouseTablesCheckSuiteRunsListParams,
    options?: RequestInit
): Promise<PaginatedDataQualitySuiteRunListApi> => {
    return apiMutator<PaginatedDataQualitySuiteRunListApi>(
        getWarehouseTablesCheckSuiteRunsListUrl(projectId, tableId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseTablesCheckSuiteRunsRetrieveUrl = (projectId: string, tableId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/check_suite_runs/${id}/`
}

/**
 * Read-only reports for this subject's check-suite executions.
 */
export const warehouseTablesCheckSuiteRunsRetrieve = async (
    projectId: string,
    tableId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getWarehouseTablesCheckSuiteRunsRetrieveUrl(projectId, tableId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseTablesCheckSuiteRunsCheckRunsListUrl = (projectId: string, tableId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/check_suite_runs/${id}/check_runs/`
}

/**
 * Every check execution in this suite run.
 */
export const warehouseTablesCheckSuiteRunsCheckRunsList = async (
    projectId: string,
    tableId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckRunApi[]> => {
    return apiMutator<DataQualityCheckRunApi[]>(
        getWarehouseTablesCheckSuiteRunsCheckRunsListUrl(projectId, tableId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getWarehouseTablesChecksListUrl = (
    projectId: string,
    tableId: string,
    params?: WarehouseTablesChecksListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/`
}

/**
 * CRUD for one subject's checks, plus the actions that run them and report on them.
 */
export const warehouseTablesChecksList = async (
    projectId: string,
    tableId: string,
    params?: WarehouseTablesChecksListParams,
    options?: RequestInit
): Promise<PaginatedDataQualityCheckListApi> => {
    return apiMutator<PaginatedDataQualityCheckListApi>(getWarehouseTablesChecksListUrl(projectId, tableId, params), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseTablesChecksCreateUrl = (projectId: string, tableId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/`
}

/**
 * Create a check on this table or view, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const warehouseTablesChecksCreate = async (
    projectId: string,
    tableId: string,
    dataQualityCheckApi: NonReadonly<DataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getWarehouseTablesChecksCreateUrl(projectId, tableId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityCheckApi),
    })
}

export const getWarehouseTablesChecksRetrieveUrl = (projectId: string, tableId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/${id}/`
}

/**
 * CRUD for one subject's checks, plus the actions that run them and report on them.
 */
export const warehouseTablesChecksRetrieve = async (
    projectId: string,
    tableId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getWarehouseTablesChecksRetrieveUrl(projectId, tableId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseTablesChecksUpdateUrl = (projectId: string, tableId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/${id}/`
}

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const warehouseTablesChecksUpdate = async (
    projectId: string,
    tableId: string,
    id: string,
    dataQualityCheckApi: NonReadonly<DataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getWarehouseTablesChecksUpdateUrl(projectId, tableId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityCheckApi),
    })
}

export const getWarehouseTablesChecksPartialUpdateUrl = (projectId: string, tableId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/${id}/`
}

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const warehouseTablesChecksPartialUpdate = async (
    projectId: string,
    tableId: string,
    id: string,
    patchedDataQualityCheckApi?: NonReadonly<PatchedDataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getWarehouseTablesChecksPartialUpdateUrl(projectId, tableId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataQualityCheckApi),
    })
}

export const getWarehouseTablesChecksDestroyUrl = (projectId: string, tableId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/${id}/`
}

/**
 * CRUD for one subject's checks, plus the actions that run them and report on them.
 */
export const warehouseTablesChecksDestroy = async (
    projectId: string,
    tableId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWarehouseTablesChecksDestroyUrl(projectId, tableId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getWarehouseTablesChecksRunCreateUrl = (projectId: string, tableId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/${id}/run/`
}

/**
 * Run this check now. Returns the suite run to poll for the report.
 */
export const warehouseTablesChecksRunCreate = async (
    projectId: string,
    tableId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getWarehouseTablesChecksRunCreateUrl(projectId, tableId, id), {
        ...options,
        method: 'POST',
    })
}

export const getWarehouseTablesChecksRunsListUrl = (projectId: string, tableId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/${id}/runs/`
}

/**
 * Recent run history for this check, newest first.
 */
export const warehouseTablesChecksRunsList = async (
    projectId: string,
    tableId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckRunApi[]> => {
    return apiMutator<DataQualityCheckRunApi[]>(getWarehouseTablesChecksRunsListUrl(projectId, tableId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseTablesChecksCheckTypesListUrl = (projectId: string, tableId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/check_types/`
}

/**
 * The check types this project can author, with the JSON schema of each type's config.
 */
export const warehouseTablesChecksCheckTypesList = async (
    projectId: string,
    tableId: string,
    options?: RequestInit
): Promise<DataQualityCheckTypeApi[]> => {
    return apiMutator<DataQualityCheckTypeApi[]>(getWarehouseTablesChecksCheckTypesListUrl(projectId, tableId), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseTablesChecksHealthRetrieveUrl = (projectId: string, tableId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/health/`
}

/**
 * Health rollup for this table or view, from the denormalized status of its checks.
 */
export const warehouseTablesChecksHealthRetrieve = async (
    projectId: string,
    tableId: string,
    options?: RequestInit
): Promise<DataQualitySubjectHealthApi> => {
    return apiMutator<DataQualitySubjectHealthApi>(getWarehouseTablesChecksHealthRetrieveUrl(projectId, tableId), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseTablesChecksRunAllCreateUrl = (projectId: string, tableId: string) => {
    return `/api/projects/${projectId}/warehouse_tables/${tableId}/checks/run_all/`
}

/**
 * Run every enabled check on this table or view. Returns the suite run to poll.
 */
export const warehouseTablesChecksRunAllCreate = async (
    projectId: string,
    tableId: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getWarehouseTablesChecksRunAllCreateUrl(projectId, tableId), {
        ...options,
        method: 'POST',
    })
}
