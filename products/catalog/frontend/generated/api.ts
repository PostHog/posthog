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
    CatalogColumnDTOApi,
    CatalogNodeDTOApi,
    CatalogNodesListParams,
    CatalogRelationshipDTOApi,
    PaginatedCatalogNodeDTOListApi,
    PatchedUpdateColumnInputApi,
    PatchedUpdateNodeInputApi,
    PatchedUpdateRelationshipInputApi,
    ProposeRelationshipInputApi,
    UpsertColumnInputApi,
    UpsertNodeInputApi,
} from './api.schemas'

export const getCatalogColumnsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/catalog/columns/`
}

/**
 * Upsert a column on a catalog node with its typing and description.
 */
export const catalogColumnsCreate = async (
    projectId: string,
    upsertColumnInputApi: UpsertColumnInputApi,
    options?: RequestInit
): Promise<CatalogColumnDTOApi> => {
    return apiMutator<CatalogColumnDTOApi>(getCatalogColumnsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(upsertColumnInputApi),
    })
}

export const getCatalogColumnsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/catalog/columns/${id}/`
}

/**
 * Retrieve a single column.
 */
export const catalogColumnsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CatalogColumnDTOApi> => {
    return apiMutator<CatalogColumnDTOApi>(getCatalogColumnsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCatalogColumnsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/catalog/columns/${id}/`
}

/**
 * Update a column's description, semantic type, PII class, or confidence.
 */
export const catalogColumnsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateColumnInputApi?: PatchedUpdateColumnInputApi,
    options?: RequestInit
): Promise<CatalogColumnDTOApi> => {
    return apiMutator<CatalogColumnDTOApi>(getCatalogColumnsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateColumnInputApi),
    })
}

export const getCatalogNodesListUrl = (projectId: string, params?: CatalogNodesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/catalog/nodes/?${stringifiedParams}`
        : `/api/projects/${projectId}/catalog/nodes/`
}

/**
 * List all catalog nodes for the team, ordered by business domain then name.
 */
export const catalogNodesList = async (
    projectId: string,
    params?: CatalogNodesListParams,
    options?: RequestInit
): Promise<PaginatedCatalogNodeDTOListApi> => {
    return apiMutator<PaginatedCatalogNodeDTOListApi>(getCatalogNodesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCatalogNodesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/catalog/nodes/`
}

/**
 * Upsert a catalog node and its agent-authored descriptions.
 */
export const catalogNodesCreate = async (
    projectId: string,
    upsertNodeInputApi: UpsertNodeInputApi,
    options?: RequestInit
): Promise<CatalogNodeDTOApi> => {
    return apiMutator<CatalogNodeDTOApi>(getCatalogNodesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(upsertNodeInputApi),
    })
}

export const getCatalogNodesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/catalog/nodes/${id}/`
}

/**
 * Retrieve a single catalog node with its columns.
 */
export const catalogNodesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CatalogNodeDTOApi> => {
    return apiMutator<CatalogNodeDTOApi>(getCatalogNodesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCatalogNodesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/catalog/nodes/${id}/`
}

/**
 * Update editable fields on a catalog node — used by the detail page.
 */
export const catalogNodesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateNodeInputApi?: PatchedUpdateNodeInputApi,
    options?: RequestInit
): Promise<CatalogNodeDTOApi> => {
    return apiMutator<CatalogNodeDTOApi>(getCatalogNodesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateNodeInputApi),
    })
}

export const getCatalogRelationshipsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/catalog/relationships/`
}

/**
 * Propose a relationship between two catalog nodes.
 */
export const catalogRelationshipsCreate = async (
    projectId: string,
    proposeRelationshipInputApi: ProposeRelationshipInputApi,
    options?: RequestInit
): Promise<CatalogRelationshipDTOApi> => {
    return apiMutator<CatalogRelationshipDTOApi>(getCatalogRelationshipsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(proposeRelationshipInputApi),
    })
}

export const getCatalogRelationshipsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/catalog/relationships/${id}/`
}

/**
 * Retrieve a single relationship.
 */
export const catalogRelationshipsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CatalogRelationshipDTOApi> => {
    return apiMutator<CatalogRelationshipDTOApi>(getCatalogRelationshipsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCatalogRelationshipsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/catalog/relationships/${id}/`
}

/**
 * Accept, reject, or annotate a relationship proposal.
 */
export const catalogRelationshipsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateRelationshipInputApi?: PatchedUpdateRelationshipInputApi,
    options?: RequestInit
): Promise<CatalogRelationshipDTOApi> => {
    return apiMutator<CatalogRelationshipDTOApi>(getCatalogRelationshipsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateRelationshipInputApi),
    })
}
