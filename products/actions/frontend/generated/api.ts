/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    ActionApi,
    ActionsCreateParams,
    ActionsDestroyParams,
    ActionsListParams,
    ActionsPartialUpdateParams,
    ActionsRetrieveParams,
    ActionsUpdateParams,
    PaginatedActionListApi,
    PatchedActionApi,
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

export const getActionsListUrl = (projectId: string, params?: ActionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/actions/?${stringifiedParams}`
        : `/api/projects/${projectId}/actions/`
}

export const actionsList = async (
    projectId: string,
    params?: ActionsListParams,
    options?: RequestInit
): Promise<PaginatedActionListApi> => {
    return apiMutator<PaginatedActionListApi>(getActionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getActionsCreateUrl = (projectId: string, params?: ActionsCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/actions/?${stringifiedParams}`
        : `/api/projects/${projectId}/actions/`
}

export const actionsCreate = async (
    projectId: string,
    actionApi: NonReadonly<ActionApi>,
    params?: ActionsCreateParams,
    options?: RequestInit
): Promise<ActionApi> => {
    return apiMutator<ActionApi>(getActionsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(actionApi),
    })
}

export const getActionsRetrieveUrl = (projectId: string, id: number, params?: ActionsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/actions/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/actions/${id}/`
}

export const actionsRetrieve = async (
    projectId: string,
    id: number,
    params?: ActionsRetrieveParams,
    options?: RequestInit
): Promise<ActionApi> => {
    return apiMutator<ActionApi>(getActionsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getActionsUpdateUrl = (projectId: string, id: number, params?: ActionsUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/actions/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/actions/${id}/`
}

export const actionsUpdate = async (
    projectId: string,
    id: number,
    actionApi: NonReadonly<ActionApi>,
    params?: ActionsUpdateParams,
    options?: RequestInit
): Promise<ActionApi> => {
    return apiMutator<ActionApi>(getActionsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(actionApi),
    })
}

export const getActionsPartialUpdateUrl = (projectId: string, id: number, params?: ActionsPartialUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/actions/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/actions/${id}/`
}

export const actionsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedActionApi: NonReadonly<PatchedActionApi>,
    params?: ActionsPartialUpdateParams,
    options?: RequestInit
): Promise<ActionApi> => {
    return apiMutator<ActionApi>(getActionsPartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedActionApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getActionsDestroyUrl = (projectId: string, id: number, params?: ActionsDestroyParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/actions/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/actions/${id}/`
}

export const actionsDestroy = async (
    projectId: string,
    id: number,
    params?: ActionsDestroyParams,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getActionsDestroyUrl(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}
