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
    DataQualityCheckCreateApi,
    DataQualityCheckRunApi,
    DataQualityCheckScheduleApi,
    DataQualityCheckTypeApi,
    DataQualityChecksCheckTypesListParams,
    DataQualityChecksHealthListParams,
    DataQualityChecksListParams,
    DataQualityChecksOutputSchemaRetrieveParams,
    DataQualityChecksScheduleRetrieveParams,
    DataQualityMetricSubjectApi,
    DataQualityOutputSchemaApi,
    DataQualityRunRequestApi,
    DataQualityRunsListParams,
    DataQualitySubjectApi,
    DataQualitySubjectHealthApi,
    DataQualitySubjectScheduleApi,
    DataQualitySuiteRunApi,
    PaginatedDataQualityOverviewCheckListApi,
    PaginatedDataQualitySuiteRunListApi,
    PatchedDataQualityCheckApi,
    PatchedDataQualityCheckScheduleUpdateApi,
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
 * Every check in the project. Narrow it to one subject with subject_type and subject_uuid, or to one assertion with check_type.
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

export const getDataQualityChecksCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality_checks/`
}

/**
 * Create a check on the table, view or metric named by subject_type and subject_uuid, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const dataQualityChecksCreate = async (
    projectId: string,
    dataQualityCheckCreateApi: NonReadonly<DataQualityCheckCreateApi>,
    options?: RequestInit
): Promise<DataQualityCheckCreateApi> => {
    return apiMutator<DataQualityCheckCreateApi>(getDataQualityChecksCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataQualityCheckCreateApi),
    })
}

export const getDataQualityChecksRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality_checks/${id}/`
}

/**
 * Every check in the project: authoring, running, results, health, and schedules.
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
    return `/api/projects/${projectId}/data_quality_checks/${id}/`
}

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The subject it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
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
    return `/api/projects/${projectId}/data_quality_checks/${id}/`
}

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The subject it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
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
    return `/api/projects/${projectId}/data_quality_checks/${id}/`
}

/**
 * Every check in the project: authoring, running, results, health, and schedules.
 */
export const dataQualityChecksDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataQualityChecksDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDataQualityChecksRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality_checks/${id}/run/`
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
    return `/api/projects/${projectId}/data_quality_checks/${id}/runs/`
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

export const getDataQualityChecksCheckTypesListUrl = (
    projectId: string,
    params?: DataQualityChecksCheckTypesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality_checks/check_types/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality_checks/check_types/`
}

/**
 * The check types this project can author, with the JSON schema of each type's config. Pass subject_type to narrow it to the types that kind of subject supports.
 */
export const dataQualityChecksCheckTypesList = async (
    projectId: string,
    params?: DataQualityChecksCheckTypesListParams,
    options?: RequestInit
): Promise<DataQualityCheckTypeApi[]> => {
    return apiMutator<DataQualityCheckTypeApi[]>(getDataQualityChecksCheckTypesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksHealthListUrl = (projectId: string, params?: DataQualityChecksHealthListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality_checks/health/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality_checks/health/`
}

/**
 * Health rollup per subject, for every subject in the project that has checks. Narrow it to one subject with subject_type and subject_uuid.
 */
export const dataQualityChecksHealthList = async (
    projectId: string,
    params?: DataQualityChecksHealthListParams,
    options?: RequestInit
): Promise<DataQualitySubjectHealthApi[]> => {
    return apiMutator<DataQualitySubjectHealthApi[]>(getDataQualityChecksHealthListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksMetricSubjectsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality_checks/metric_subjects/`
}

/**
 * Every check in the project: authoring, running, results, health, and schedules.
 */
export const dataQualityChecksMetricSubjectsList = async (
    projectId: string,
    options?: RequestInit
): Promise<DataQualityMetricSubjectApi[]> => {
    return apiMutator<DataQualityMetricSubjectApi[]>(getDataQualityChecksMetricSubjectsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksOutputSchemaRetrieveUrl = (
    projectId: string,
    params?: DataQualityChecksOutputSchemaRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality_checks/output_schema/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality_checks/output_schema/`
}

/**
 * Columns the subject's query returns, for authoring a check against them. Metrics only.
 */
export const dataQualityChecksOutputSchemaRetrieve = async (
    projectId: string,
    params?: DataQualityChecksOutputSchemaRetrieveParams,
    options?: RequestInit
): Promise<DataQualityOutputSchemaApi> => {
    return apiMutator<DataQualityOutputSchemaApi>(getDataQualityChecksOutputSchemaRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksScheduleRetrieveUrl = (
    projectId: string,
    params?: DataQualityChecksScheduleRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_quality_checks/schedule/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_quality_checks/schedule/`
}

/**
 * The schedule every enabled check on this subject runs on.
 */
export const dataQualityChecksScheduleRetrieve = async (
    projectId: string,
    params?: DataQualityChecksScheduleRetrieveParams,
    options?: RequestInit
): Promise<DataQualityCheckScheduleApi> => {
    return apiMutator<DataQualityCheckScheduleApi>(getDataQualityChecksScheduleRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksSchedulePartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality_checks/schedule/`
}

/**
 * Change how often this subject's checks run, or stop running them automatically. Name the subject with subject_type and subject_uuid in the body.
 */
export const dataQualityChecksSchedulePartialUpdate = async (
    projectId: string,
    patchedDataQualityCheckScheduleUpdateApi?: PatchedDataQualityCheckScheduleUpdateApi,
    options?: RequestInit
): Promise<DataQualityCheckScheduleApi> => {
    return apiMutator<DataQualityCheckScheduleApi>(getDataQualityChecksSchedulePartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataQualityCheckScheduleUpdateApi),
    })
}

export const getDataQualityChecksSchedulesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality_checks/schedules/`
}

/**
 * The schedule of every subject in the project whose checks run on one, for the checks the caller may read. One request for the overview instead of one per subject.
 */
export const dataQualityChecksSchedulesList = async (
    projectId: string,
    options?: RequestInit
): Promise<DataQualitySubjectScheduleApi[]> => {
    return apiMutator<DataQualitySubjectScheduleApi[]>(getDataQualityChecksSchedulesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDataQualityChecksSubjectsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_quality_checks/subjects/`
}

/**
 * Everything in this project you can author a check on, with each subject's columns.
 */
export const dataQualityChecksSubjectsList = async (
    projectId: string,
    options?: RequestInit
): Promise<DataQualitySubjectApi[]> => {
    return apiMutator<DataQualitySubjectApi[]>(getDataQualityChecksSubjectsListUrl(projectId), {
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
 * Every check-suite run in the project, newest first. Narrow it to one subject with subject_type and subject_uuid.
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
 * Run checks now: the ones named by check_ids, every enabled check on the subject named by subject_type and subject_uuid, or every enabled check in the project when neither is given. Returns the suite run to poll for the report.
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
 * Check-suite executions: start one over a selection, and read every run the project has had.
 *
 * A suite run may sweep several subjects at once -- a manual project-wide run, a materialization,
 * a source sync -- so it is reported here rather than under any one of them.
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

export const getDataQualityRunsCheckRunsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_quality_runs/${id}/check_runs/`
}

/**
 * Every check execution in this suite run.
 */
export const dataQualityRunsCheckRunsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DataQualityCheckRunApi[]> => {
    return apiMutator<DataQualityCheckRunApi[]>(getDataQualityRunsCheckRunsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}
