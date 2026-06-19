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
    AgentMemoryFileDestroyParams,
    AgentMemoryListParams,
    AgentMemoryReadRetrieveParams,
    MemoryAppendInputApi,
    MemoryDeleteResponseApi,
    MemoryFileApi,
    MemoryWriteInputApi,
    PaginatedMemoryFileSummaryListApi,
} from './api.schemas'

export const getAgentMemoryListUrl = (projectId: string, params?: AgentMemoryListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_memory/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_memory/`
}

/**
 * List the team's memory files (metadata only, no bodies).
 */
export const agentMemoryList = async (
    projectId: string,
    params?: AgentMemoryListParams,
    options?: RequestInit
): Promise<PaginatedMemoryFileSummaryListApi> => {
    return apiMutator<PaginatedMemoryFileSummaryListApi>(getAgentMemoryListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentMemoryAppendCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agent_memory/append/`
}

/**
 * Append or replace a single markdown section atomically — never clobbers concurrent edits.
 */
export const agentMemoryAppendCreate = async (
    projectId: string,
    memoryAppendInputApi: MemoryAppendInputApi,
    options?: RequestInit
): Promise<MemoryFileApi> => {
    return apiMutator<MemoryFileApi>(getAgentMemoryAppendCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(memoryAppendInputApi),
    })
}

export const getAgentMemoryFileDestroyUrl = (projectId: string, params: AgentMemoryFileDestroyParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_memory/file/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_memory/file/`
}

/**
 * Delete a memory file. Idempotent — deleting a missing file returns deleted=false.
 */
export const agentMemoryFileDestroy = async (
    projectId: string,
    params: AgentMemoryFileDestroyParams,
    options?: RequestInit
): Promise<MemoryDeleteResponseApi> => {
    return apiMutator<MemoryDeleteResponseApi>(getAgentMemoryFileDestroyUrl(projectId, params), {
        ...options,
        method: 'DELETE',
    })
}

export const getAgentMemoryReadRetrieveUrl = (projectId: string, params: AgentMemoryReadRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/agent_memory/read/?${stringifiedParams}`
        : `/api/projects/${projectId}/agent_memory/read/`
}

/**
 * Read a single memory file by path.
 */
export const agentMemoryReadRetrieve = async (
    projectId: string,
    params: AgentMemoryReadRetrieveParams,
    options?: RequestInit
): Promise<MemoryFileApi> => {
    return apiMutator<MemoryFileApi>(getAgentMemoryReadRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAgentMemoryWriteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/agent_memory/write/`
}

/**
 * Compare-and-set write of a whole file. Returns 409 on a version mismatch.
 */
export const agentMemoryWriteCreate = async (
    projectId: string,
    memoryWriteInputApi: MemoryWriteInputApi,
    options?: RequestInit
): Promise<MemoryFileApi> => {
    return apiMutator<MemoryFileApi>(getAgentMemoryWriteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(memoryWriteInputApi),
    })
}
