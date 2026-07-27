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
    BusinessKnowledgeDocumentsSearchListParams,
    BusinessKnowledgeDocumentsWindowListParams,
    BusinessKnowledgeGapSuggestionsListParams,
    BusinessKnowledgeSourcesListParams,
    BusinessKnowledgeSourcesTextRetrieve200,
    CreateTextSourceApi,
    GapActionApi,
    GapTopicActionApi,
    GapTopicActionResultApi,
    KnowledgeDocumentWindowApi,
    KnowledgeGapSuggestionApi,
    KnowledgeSearchResultApi,
    KnowledgeSourceApi,
    PaginatedKnowledgeGapSuggestionListApi,
    PaginatedKnowledgeSourceListApi,
    PatchedUpdateTextSourceApi,
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

export const getBusinessKnowledgeDocumentsWindowListUrl = (
    projectId: string,
    id: string,
    params: BusinessKnowledgeDocumentsWindowListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/documents/${id}/window/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/documents/${id}/window/`
}

/**
 * Read-only access to parsed knowledge documents. Exposes hybrid search
 * (``search``) and a drill-down window (``window``) so an agent (PHAI or
 * MCP) can find and explore business knowledge chunks.
 */
export const businessKnowledgeDocumentsWindowList = async (
    projectId: string,
    id: string,
    params: BusinessKnowledgeDocumentsWindowListParams,
    options?: RequestInit
): Promise<KnowledgeDocumentWindowApi[]> => {
    return apiMutator<KnowledgeDocumentWindowApi[]>(getBusinessKnowledgeDocumentsWindowListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeDocumentsSearchListUrl = (
    projectId: string,
    params: BusinessKnowledgeDocumentsSearchListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/documents/search/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/documents/search/`
}

/**
 * Read-only access to parsed knowledge documents. Exposes hybrid search
 * (``search``) and a drill-down window (``window``) so an agent (PHAI or
 * MCP) can find and explore business knowledge chunks.
 */
export const businessKnowledgeDocumentsSearchList = async (
    projectId: string,
    params: BusinessKnowledgeDocumentsSearchListParams,
    options?: RequestInit
): Promise<KnowledgeSearchResultApi[]> => {
    return apiMutator<KnowledgeSearchResultApi[]>(getBusinessKnowledgeDocumentsSearchListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeGapSuggestionsListUrl = (
    projectId: string,
    params?: BusinessKnowledgeGapSuggestionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/gap_suggestions/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/gap_suggestions/`
}

/**
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const businessKnowledgeGapSuggestionsList = async (
    projectId: string,
    params?: BusinessKnowledgeGapSuggestionsListParams,
    options?: RequestInit
): Promise<PaginatedKnowledgeGapSuggestionListApi> => {
    return apiMutator<PaginatedKnowledgeGapSuggestionListApi>(
        getBusinessKnowledgeGapSuggestionsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getBusinessKnowledgeGapSuggestionsAcceptCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/gap_suggestions/${id}/accept/`
}

/**
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const businessKnowledgeGapSuggestionsAcceptCreate = async (
    projectId: string,
    id: string,
    gapActionApi?: GapActionApi,
    options?: RequestInit
): Promise<KnowledgeGapSuggestionApi> => {
    return apiMutator<KnowledgeGapSuggestionApi>(getBusinessKnowledgeGapSuggestionsAcceptCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gapActionApi),
    })
}

export const getBusinessKnowledgeGapSuggestionsDismissCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/gap_suggestions/${id}/dismiss/`
}

/**
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const businessKnowledgeGapSuggestionsDismissCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<KnowledgeGapSuggestionApi> => {
    return apiMutator<KnowledgeGapSuggestionApi>(getBusinessKnowledgeGapSuggestionsDismissCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getBusinessKnowledgeGapSuggestionsAcceptTopicCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/gap_suggestions/accept_topic/`
}

/**
 * Accept all pending suggestions for a normalized topic cluster.
 */
export const businessKnowledgeGapSuggestionsAcceptTopicCreate = async (
    projectId: string,
    gapTopicActionApi: GapTopicActionApi,
    options?: RequestInit
): Promise<GapTopicActionResultApi> => {
    return apiMutator<GapTopicActionResultApi>(getBusinessKnowledgeGapSuggestionsAcceptTopicCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gapTopicActionApi),
    })
}

export const getBusinessKnowledgeGapSuggestionsDismissTopicCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/gap_suggestions/dismiss_topic/`
}

/**
 * Dismiss all pending suggestions for a normalized topic cluster.
 */
export const businessKnowledgeGapSuggestionsDismissTopicCreate = async (
    projectId: string,
    gapTopicActionApi: GapTopicActionApi,
    options?: RequestInit
): Promise<GapTopicActionResultApi> => {
    return apiMutator<GapTopicActionResultApi>(getBusinessKnowledgeGapSuggestionsDismissTopicCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gapTopicActionApi),
    })
}

export const getBusinessKnowledgeSourcesListUrl = (projectId: string, params?: BusinessKnowledgeSourcesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/sources/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/sources/`
}

export const businessKnowledgeSourcesList = async (
    projectId: string,
    params?: BusinessKnowledgeSourcesListParams,
    options?: RequestInit
): Promise<PaginatedKnowledgeSourceListApi> => {
    return apiMutator<PaginatedKnowledgeSourceListApi>(getBusinessKnowledgeSourcesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSourcesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/`
}

export const businessKnowledgeSourcesCreate = async (
    projectId: string,
    createTextSourceApi: CreateTextSourceApi,
    options?: RequestInit
): Promise<KnowledgeSourceApi> => {
    return apiMutator<KnowledgeSourceApi>(getBusinessKnowledgeSourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createTextSourceApi),
    })
}

export const getBusinessKnowledgeSourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/`
}

export const businessKnowledgeSourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<KnowledgeSourceApi> => {
    return apiMutator<KnowledgeSourceApi>(getBusinessKnowledgeSourcesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/`
}

export const businessKnowledgeSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateTextSourceApi?: PatchedUpdateTextSourceApi,
    options?: RequestInit
): Promise<KnowledgeSourceApi> => {
    return apiMutator<KnowledgeSourceApi>(getBusinessKnowledgeSourcesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateTextSourceApi),
    })
}

export const getBusinessKnowledgeSourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/`
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
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/refresh/`
}

export const businessKnowledgeSourcesRefreshCreate = async (
    projectId: string,
    id: string,
    knowledgeSourceApi?: NonReadonly<KnowledgeSourceApi>,
    options?: RequestInit
): Promise<KnowledgeSourceApi> => {
    return apiMutator<KnowledgeSourceApi>(getBusinessKnowledgeSourcesRefreshCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(knowledgeSourceApi),
    })
}

export const getBusinessKnowledgeSourcesTextRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/text/`
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
