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
    AssignCredentialApi,
    AssignableCredentialApi,
    BindCredentialApi,
    GatewayApi,
    GatewayBoundCredentialsApi,
    GatewaysListParams,
    PaginatedGatewayListApi,
    PatchedGatewayApi,
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

export const getGatewaysListUrl = (projectId: string, params?: GatewaysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/gateways/?${stringifiedParams}`
        : `/api/projects/${projectId}/gateways/`
}

export const gatewaysList = async (
    projectId: string,
    params?: GatewaysListParams,
    options?: RequestInit
): Promise<PaginatedGatewayListApi> => {
    return apiMutator<PaginatedGatewayListApi>(getGatewaysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGatewaysCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/gateways/`
}

export const gatewaysCreate = async (
    projectId: string,
    gatewayApi: NonReadonly<GatewayApi>,
    options?: RequestInit
): Promise<GatewayApi> => {
    return apiMutator<GatewayApi>(getGatewaysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gatewayApi),
    })
}

export const getGatewaysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/gateways/${id}/`
}

export const gatewaysRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<GatewayApi> => {
    return apiMutator<GatewayApi>(getGatewaysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getGatewaysUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/gateways/${id}/`
}

export const gatewaysUpdate = async (
    projectId: string,
    id: string,
    gatewayApi: NonReadonly<GatewayApi>,
    options?: RequestInit
): Promise<GatewayApi> => {
    return apiMutator<GatewayApi>(getGatewaysUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gatewayApi),
    })
}

export const getGatewaysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/gateways/${id}/`
}

export const gatewaysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedGatewayApi?: NonReadonly<PatchedGatewayApi>,
    options?: RequestInit
): Promise<GatewayApi> => {
    return apiMutator<GatewayApi>(getGatewaysPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedGatewayApi),
    })
}

export const getGatewaysDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/gateways/${id}/`
}

export const gatewaysDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getGatewaysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getGatewaysAssignCredentialCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/gateways/${id}/assign_credential/`
}

/**
 * Assign one of your own unassigned personal API keys to this gateway.

An unbound key has no team boundary, so only its owner may assign it — hence
the user filter (unlike bind_credential, which moves the team's already-bound keys).
 */
export const gatewaysAssignCredentialCreate = async (
    projectId: string,
    id: string,
    assignCredentialApi: AssignCredentialApi,
    options?: RequestInit
): Promise<GatewayApi> => {
    return apiMutator<GatewayApi>(getGatewaysAssignCredentialCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(assignCredentialApi),
    })
}

export const getGatewaysCredentialsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/gateways/${id}/credentials/`
}

/**
 * List the personal API keys and OAuth applications that attribute usage to this gateway.
 */
export const gatewaysCredentialsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<GatewayBoundCredentialsApi> => {
    return apiMutator<GatewayBoundCredentialsApi>(getGatewaysCredentialsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getGatewaysUnassignCredentialCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/gateways/${id}/unassign_credential/`
}

/**
 * Remove a credential from this gateway, leaving it unassigned.

You can remove your own personal key; removing anyone else's key (or an OAuth
application) is admin-only, like the cross-gateway move.
 */
export const gatewaysUnassignCredentialCreate = async (
    projectId: string,
    id: string,
    bindCredentialApi: BindCredentialApi,
    options?: RequestInit
): Promise<GatewayApi> => {
    return apiMutator<GatewayApi>(getGatewaysUnassignCredentialCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bindCredentialApi),
    })
}

export const getGatewaysAssignableCredentialsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/gateways/assignable_credentials/`
}

/**
 * Your personal API keys that carry the llm_gateway:read scope but aren't assigned to a gateway yet.
 */
export const gatewaysAssignableCredentialsList = async (
    projectId: string,
    options?: RequestInit
): Promise<AssignableCredentialApi[]> => {
    return apiMutator<AssignableCredentialApi[]>(getGatewaysAssignableCredentialsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
