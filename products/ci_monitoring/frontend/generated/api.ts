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
    CIHealthApi,
    CIRunApi,
    CiMonitoringReposListParams,
    CiMonitoringRunsListParams,
    CiMonitoringTestsExecutionsListParams,
    CiMonitoringTestsListParams,
    CreateQuarantineInputApi,
    CreateRepoInputApi,
    PaginatedCIRunListApi,
    PaginatedRepoListApi,
    PaginatedTestCaseListApi,
    PaginatedTestExecutionListApi,
    QuarantineApi,
    RepoApi,
    TestCaseApi,
} from './api.schemas'

export const getCiMonitoringQuarantinesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ci_monitoring/quarantines/`
}

export const ciMonitoringQuarantinesCreate = async (
    projectId: string,
    createQuarantineInputApi: CreateQuarantineInputApi,
    options?: RequestInit
): Promise<QuarantineApi> => {
    return apiMutator<QuarantineApi>(getCiMonitoringQuarantinesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createQuarantineInputApi),
    })
}

export const getCiMonitoringQuarantinesResolveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/ci_monitoring/quarantines/${id}/resolve/`
}

export const ciMonitoringQuarantinesResolveCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<QuarantineApi> => {
    return apiMutator<QuarantineApi>(getCiMonitoringQuarantinesResolveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getCiMonitoringReposListUrl = (projectId: string, params?: CiMonitoringReposListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/ci_monitoring/repos/?${stringifiedParams}`
        : `/api/projects/${projectId}/ci_monitoring/repos/`
}

export const ciMonitoringReposList = async (
    projectId: string,
    params?: CiMonitoringReposListParams,
    options?: RequestInit
): Promise<PaginatedRepoListApi> => {
    return apiMutator<PaginatedRepoListApi>(getCiMonitoringReposListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCiMonitoringReposCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ci_monitoring/repos/`
}

export const ciMonitoringReposCreate = async (
    projectId: string,
    createRepoInputApi: CreateRepoInputApi,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getCiMonitoringReposCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createRepoInputApi),
    })
}

export const getCiMonitoringReposRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/ci_monitoring/repos/${id}/`
}

export const ciMonitoringReposRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getCiMonitoringReposRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCiMonitoringReposHealthRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/ci_monitoring/repos/${id}/health/`
}

export const ciMonitoringReposHealthRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CIHealthApi> => {
    return apiMutator<CIHealthApi>(getCiMonitoringReposHealthRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCiMonitoringRunsListUrl = (projectId: string, params?: CiMonitoringRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/ci_monitoring/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/ci_monitoring/runs/`
}

export const ciMonitoringRunsList = async (
    projectId: string,
    params?: CiMonitoringRunsListParams,
    options?: RequestInit
): Promise<PaginatedCIRunListApi> => {
    return apiMutator<PaginatedCIRunListApi>(getCiMonitoringRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCiMonitoringRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/ci_monitoring/runs/${id}/`
}

export const ciMonitoringRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CIRunApi> => {
    return apiMutator<CIRunApi>(getCiMonitoringRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCiMonitoringTestsListUrl = (projectId: string, params?: CiMonitoringTestsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/ci_monitoring/tests/?${stringifiedParams}`
        : `/api/projects/${projectId}/ci_monitoring/tests/`
}

export const ciMonitoringTestsList = async (
    projectId: string,
    params?: CiMonitoringTestsListParams,
    options?: RequestInit
): Promise<PaginatedTestCaseListApi> => {
    return apiMutator<PaginatedTestCaseListApi>(getCiMonitoringTestsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCiMonitoringTestsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/ci_monitoring/tests/${id}/`
}

export const ciMonitoringTestsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TestCaseApi> => {
    return apiMutator<TestCaseApi>(getCiMonitoringTestsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCiMonitoringTestsExecutionsListUrl = (
    projectId: string,
    id: string,
    params?: CiMonitoringTestsExecutionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/ci_monitoring/tests/${id}/executions/?${stringifiedParams}`
        : `/api/projects/${projectId}/ci_monitoring/tests/${id}/executions/`
}

export const ciMonitoringTestsExecutionsList = async (
    projectId: string,
    id: string,
    params?: CiMonitoringTestsExecutionsListParams,
    options?: RequestInit
): Promise<PaginatedTestExecutionListApi> => {
    return apiMutator<PaginatedTestExecutionListApi>(getCiMonitoringTestsExecutionsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}
