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
    KnowledgeSourceApi,
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

export const getBusinessKnowledgeSourcesListUrl = (projectId: string, params?: BusinessKnowledgeSourcesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
    patchedUpdateTextSourceApi: PatchedUpdateTextSourceApi,
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
    knowledgeSourceApi: NonReadonly<KnowledgeSourceApi>,
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
