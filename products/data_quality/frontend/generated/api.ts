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
    DataQualityCheckSuiteRunsListParams,
    DataQualityCheckTypeApi,
    DataQualityChecksHealthRetrieveParams,
    DataQualityChecksListParams,
    DataQualityRunSubjectRequestApi,
    DataQualitySubjectHealthApi,
    DataQualitySuiteRunApi,
    PaginatedDataQualityCheckListApi,
    PaginatedDataQualitySuiteRunListApi,
    PatchedDataQualityCheckApi,
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

export const getDataQualityCheckSuiteRunsListUrl = (
    projectId: string,
    params?: DataQualityCheckSuiteRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality/check_suite_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality/check_suite_runs/`
}

/**
 * Read-only reports for batches of check executions.
 */
export const dataQualityCheckSuiteRunsList = async (
    projectId: string,
    params?: DataQualityCheckSuiteRunsListParams,
    options?: RequestInit
): Promise<PaginatedDataQualitySuiteRunListApi> => {
    return apiMutator<PaginatedDataQualitySuiteRunListApi>(getDataQualityCheckSuiteRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityCheckSuiteRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality/check_suite_runs/${id}/`
}

/**
 * Read-only reports for batches of check executions.
 */
export const dataQualityCheckSuiteRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getDataQualityCheckSuiteRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityCheckSuiteRunsCheckRunsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality/check_suite_runs/${id}/check_runs/`
}

/**
 * Every check execution in this suite run.
 */
export const dataQualityCheckSuiteRunsCheckRunsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckRunApi[]> => {
    return apiMutator<DataQualityCheckRunApi[]>(getDataQualityCheckSuiteRunsCheckRunsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksListUrl = (projectId: string, params?: DataQualityChecksListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality/checks/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality/checks/`
}

/**
 * CRUD for data quality checks, plus the actions that run them and report on them.
 */
export const dataQualityChecksList = async (
    projectId: string,
    params?: DataQualityChecksListParams,
    options?: RequestInit
): Promise<PaginatedDataQualityCheckListApi> => {
    return apiMutator<PaginatedDataQualityCheckListApi>(getDataQualityChecksListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality/checks/`
}

/**
 * Create a check, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const dataQualityChecksCreate = async (
    projectId: string,
    dataQualityCheckApi: NonReadonly<DataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getDataQualityChecksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityCheckApi),
    })
}

export const getDataQualityChecksRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality/checks/${id}/`
}

/**
 * CRUD for data quality checks, plus the actions that run them and report on them.
 */
export const dataQualityChecksRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getDataQualityChecksRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality/checks/${id}/`
}

/**
 * CRUD for data quality checks, plus the actions that run them and report on them.
 */
export const dataQualityChecksUpdate = async (
    projectId: string,
    id: string,
    dataQualityCheckApi: NonReadonly<DataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getDataQualityChecksUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityCheckApi),
    })
}

export const getDataQualityChecksPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality/checks/${id}/`
}

/**
 * CRUD for data quality checks, plus the actions that run them and report on them.
 */
export const dataQualityChecksPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDataQualityCheckApi?: NonReadonly<PatchedDataQualityCheckApi>,
    options?: RequestInit
): Promise<DataQualityCheckApi> => {
    return apiMutator<DataQualityCheckApi>(getDataQualityChecksPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataQualityCheckApi),
    })
}

export const getDataQualityChecksDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality/checks/${id}/`
}

/**
 * CRUD for data quality checks, plus the actions that run them and report on them.
 */
export const dataQualityChecksDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataQualityChecksDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDataQualityChecksRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality/checks/${id}/run/`
}

/**
 * Run this check now. Returns the suite run to poll for the report.
 */
export const dataQualityChecksRunCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getDataQualityChecksRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getDataQualityChecksRunsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality/checks/${id}/runs/`
}

/**
 * Recent run history for this check, newest first.
 */
export const dataQualityChecksRunsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckRunApi[]> => {
    return apiMutator<DataQualityCheckRunApi[]>(getDataQualityChecksRunsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksCheckTypesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality/checks/check_types/`
}

/**
 * The check types this project can author, with the JSON schema of each type's config.
 */
export const dataQualityChecksCheckTypesList = async (
    projectId: string,
    options?: RequestInit
): Promise<DataQualityCheckTypeApi[]> => {
    return apiMutator<DataQualityCheckTypeApi[]>(getDataQualityChecksCheckTypesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksHealthRetrieveUrl = (
    projectId: string,
    params: DataQualityChecksHealthRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality/checks/health/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality/checks/health/`
}

/**
 * Health rollup for one table or view, from the denormalized status of its checks.
 */
export const dataQualityChecksHealthRetrieve = async (
    projectId: string,
    params: DataQualityChecksHealthRetrieveParams,
    options?: RequestInit
): Promise<DataQualitySubjectHealthApi> => {
    return apiMutator<DataQualitySubjectHealthApi>(getDataQualityChecksHealthRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksRunForSubjectCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality/checks/run_for_subject/`
}

/**
 * Run every enabled check on a table or view. Returns the suite run to poll for the report.
 */
export const dataQualityChecksRunForSubjectCreate = async (
    projectId: string,
    dataQualityRunSubjectRequestApi: DataQualityRunSubjectRequestApi,
    options?: RequestInit
): Promise<DataQualitySuiteRunApi> => {
    return apiMutator<DataQualitySuiteRunApi>(getDataQualityChecksRunForSubjectCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityRunSubjectRequestApi),
    })
}
