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
    DataModelingEdgesListParams,
    DataModelingNodesListParams,
    EdgeApi,
    NodeApi,
    PaginatedEdgeListApi,
    PaginatedNodeListApi,
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

export const getDataModelingEdgesListUrl = (projectId: string, params?: DataModelingEdgesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/data_modeling_edges/?${stringifiedParams}`
        : `/api/environments/${projectId}/data_modeling_edges/`
}

export const dataModelingEdgesList = async (
    projectId: string,
    params?: DataModelingEdgesListParams,
    options?: RequestInit
): Promise<PaginatedEdgeListApi> => {
    return apiMutator<PaginatedEdgeListApi>(getDataModelingEdgesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingEdgesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_modeling_edges/`
}

export const dataModelingEdgesCreate = async (
    projectId: string,
    edgeApi: NonReadonly<EdgeApi>,
    options?: RequestInit
): Promise<EdgeApi> => {
    return apiMutator<EdgeApi>(getDataModelingEdgesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(edgeApi),
    })
}

export const getDataModelingNodesListUrl = (projectId: string, params?: DataModelingNodesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/data_modeling_nodes/?${stringifiedParams}`
        : `/api/environments/${projectId}/data_modeling_nodes/`
}

export const dataModelingNodesList = async (
    projectId: string,
    params?: DataModelingNodesListParams,
    options?: RequestInit
): Promise<PaginatedNodeListApi> => {
    return apiMutator<PaginatedNodeListApi>(getDataModelingNodesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingNodesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_modeling_nodes/`
}

export const dataModelingNodesCreate = async (
    projectId: string,
    nodeApi: NonReadonly<NodeApi>,
    options?: RequestInit
): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(nodeApi),
    })
}

/**
 * Get all distinct dag_ids for the team's nodes.
 */
export const getDataModelingNodesDagIdsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_modeling_nodes/dag_ids/`
}

export const dataModelingNodesDagIdsRetrieve = async (projectId: string, options?: RequestInit): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesDagIdsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
