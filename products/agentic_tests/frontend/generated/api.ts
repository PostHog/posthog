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
    AgenticTestApi,
    AgenticTestRunApi,
    AgenticTestRunsListParams,
    AgenticTestsListParams,
    DetectFlowsRequestApi,
    DetectFlowsResponseApi,
    PaginatedAgenticTestListApi,
    PaginatedAgenticTestRunListApi,
    PatchedAgenticTestApi,
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

export const getAgenticTestRunsListUrl = (projectId: string, params?: AgenticTestRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agentic_test_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/agentic_test_runs/`
}

export const agenticTestRunsList = async (
    projectId: string,
    params?: AgenticTestRunsListParams,
    options?: RequestInit
): Promise<PaginatedAgenticTestRunListApi> => {
    return apiMutator<PaginatedAgenticTestRunListApi>(getAgenticTestRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgenticTestsListUrl = (projectId: string, params?: AgenticTestsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agentic_tests/?${stringifiedParams}`
        : `/api/projects/${projectId}/agentic_tests/`
}

export const agenticTestsList = async (
    projectId: string,
    params?: AgenticTestsListParams,
    options?: RequestInit
): Promise<PaginatedAgenticTestListApi> => {
    return apiMutator<PaginatedAgenticTestListApi>(getAgenticTestsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgenticTestsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agentic_tests/`
}

export const agenticTestsCreate = async (
    projectId: string,
    agenticTestApi: NonReadonly<AgenticTestApi>,
    options?: RequestInit
): Promise<AgenticTestApi> => {
    return apiMutator<AgenticTestApi>(getAgenticTestsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(agenticTestApi),
    })
}

export const getAgenticTestsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/`
}

export const agenticTestsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AgenticTestApi> => {
    return apiMutator<AgenticTestApi>(getAgenticTestsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAgenticTestsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/`
}

export const agenticTestsUpdate = async (
    projectId: string,
    id: string,
    agenticTestApi: NonReadonly<AgenticTestApi>,
    options?: RequestInit
): Promise<AgenticTestApi> => {
    return apiMutator<AgenticTestApi>(getAgenticTestsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(agenticTestApi),
    })
}

export const getAgenticTestsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/`
}

export const agenticTestsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAgenticTestApi?: NonReadonly<PatchedAgenticTestApi>,
    options?: RequestInit
): Promise<AgenticTestApi> => {
    return apiMutator<AgenticTestApi>(getAgenticTestsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAgenticTestApi),
    })
}

export const getAgenticTestsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/`
}

export const agenticTestsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAgenticTestsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgenticTestsActivateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/activate/`
}

/**
 * Mark a proposed or paused test as active.
 */
export const agenticTestsActivateCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AgenticTestApi> => {
    return apiMutator<AgenticTestApi>(getAgenticTestsActivateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAgenticTestsPauseCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/pause/`
}

/**
 * Mark a test as paused.
 */
export const agenticTestsPauseCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AgenticTestApi> => {
    return apiMutator<AgenticTestApi>(getAgenticTestsPauseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAgenticTestsRejectCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/reject/`
}

/**
 * Reject a proposed test. The test is kept (status=rejected) so users can restore it later.
 */
export const agenticTestsRejectCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AgenticTestApi> => {
    return apiMutator<AgenticTestApi>(getAgenticTestsRejectCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAgenticTestsRunNowCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/run_now/`
}

/**
 * Trigger an immediate run of this agentic test (blocks until complete; for long runs prefer `stream`).
 */
export const agenticTestsRunNowCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AgenticTestRunApi> => {
    return apiMutator<AgenticTestRunApi>(getAgenticTestsRunNowCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAgenticTestsStreamCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/agentic_tests/${id}/stream/`
}

/**
 * Trigger a run and stream progress as Server-Sent Events. Each event is a JSON line with `type` and `data`. A terminal event with `type='final'` carries the persisted AgenticTestRun id (`run_id`) so the client can fetch the row.
 */
export const agenticTestsStreamCreate = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAgenticTestsStreamCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAgenticTestsDetectFlowsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agentic_tests/detect_flows/`
}

/**
 * Get the latest flow-detection task for this team, if any.
 */
export const agenticTestsDetectFlowsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<DetectFlowsResponseApi> => {
    return apiMutator<DetectFlowsResponseApi>(getAgenticTestsDetectFlowsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getAgenticTestsDetectFlowsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agentic_tests/detect_flows/`
}

/**
 * Launch a sandboxed agent to analyze a GitHub repository and propose test flows.
 */
export const agenticTestsDetectFlowsCreate = async (
    projectId: string,
    detectFlowsRequestApi: DetectFlowsRequestApi,
    options?: RequestInit
): Promise<DetectFlowsResponseApi> => {
    return apiMutator<DetectFlowsResponseApi>(getAgenticTestsDetectFlowsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(detectFlowsRequestApi),
    })
}

export const getAgenticTestsDetectFlowsDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agentic_tests/detect_flows/`
}

/**
 * Dismiss the latest flow-detection task (soft-delete).
 */
export const agenticTestsDetectFlowsDestroy = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAgenticTestsDetectFlowsDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}
