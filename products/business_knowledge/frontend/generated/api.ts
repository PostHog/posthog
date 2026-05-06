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
    BusinessKnowledgeSourcesListParams,
    BusinessKnowledgeSourcesTextRetrieve200,
    CreateTextSourceApi,
    KnowledgeSourceDTOApi,
    PaginatedKnowledgeSourceDTOListApi,
    PatchedUpdateTextSourceApi,
} from './api.schemas'

export const getBusinessKnowledgeSourcesListUrl = (projectId: string, params?: BusinessKnowledgeSourcesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/business_knowledge/sources/?${stringifiedParams}`
        : `/api/environments/${projectId}/business_knowledge/sources/`
}

export const businessKnowledgeSourcesList = async (
    projectId: string,
    params?: BusinessKnowledgeSourcesListParams,
    options?: RequestInit
): Promise<PaginatedKnowledgeSourceDTOListApi> => {
    return apiMutator<PaginatedKnowledgeSourceDTOListApi>(getBusinessKnowledgeSourcesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSourcesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/business_knowledge/sources/`
}

export const businessKnowledgeSourcesCreate = async (
    projectId: string,
    createTextSourceApi: CreateTextSourceApi,
    options?: RequestInit
): Promise<KnowledgeSourceDTOApi> => {
    return apiMutator<KnowledgeSourceDTOApi>(getBusinessKnowledgeSourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createTextSourceApi),
    })
}

export const getBusinessKnowledgeSourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/business_knowledge/sources/${id}/`
}

export const businessKnowledgeSourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<KnowledgeSourceDTOApi> => {
    return apiMutator<KnowledgeSourceDTOApi>(getBusinessKnowledgeSourcesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/business_knowledge/sources/${id}/`
}

export const businessKnowledgeSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateTextSourceApi: PatchedUpdateTextSourceApi,
    options?: RequestInit
): Promise<KnowledgeSourceDTOApi> => {
    return apiMutator<KnowledgeSourceDTOApi>(getBusinessKnowledgeSourcesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateTextSourceApi),
    })
}

export const getBusinessKnowledgeSourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/business_knowledge/sources/${id}/`
}

export const businessKnowledgeSourcesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBusinessKnowledgeSourcesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getBusinessKnowledgeSourcesRefreshCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/business_knowledge/sources/${id}/refresh/`
}

export const businessKnowledgeSourcesRefreshCreate = async (
    projectId: string,
    id: string,
    knowledgeSourceDTOApi: KnowledgeSourceDTOApi,
    options?: RequestInit
): Promise<KnowledgeSourceDTOApi> => {
    return apiMutator<KnowledgeSourceDTOApi>(getBusinessKnowledgeSourcesRefreshCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(knowledgeSourceDTOApi),
    })
}

export const getBusinessKnowledgeSourcesTextRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/business_knowledge/sources/${id}/text/`
}

export const businessKnowledgeSourcesTextRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BusinessKnowledgeSourcesTextRetrieve200> => {
    return apiMutator<BusinessKnowledgeSourcesTextRetrieve200>(
        getBusinessKnowledgeSourcesTextRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}
