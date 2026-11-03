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
    DataModelingEdgesListParams,
    DataModelingNodesLineageRetrieveParams,
    DataModelingNodesListParams,
    DataModelingNodesRetrieveParams,
    DataModelingUsageListParams,
    EdgeApi,
    LineageResponseApi,
    ModelUsageApi,
    NodeApi,
    NodeResumeApi,
    NodeRunApi,
    NodeRunResponseApi,
    PaginatedEdgeSummaryListApi,
    PaginatedNodeListApi,
    PatchedEdgeApi,
    PatchedNodeApi,
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_modeling_edges/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_edges/`
}

export const dataModelingEdgesList = async (
    projectId: string,
    params?: DataModelingEdgesListParams,
    options?: RequestInit
): Promise<PaginatedEdgeSummaryListApi> => {
    return apiMutator<PaginatedEdgeSummaryListApi>(getDataModelingEdgesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingEdgesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_edges/${id}/`
}

export const dataModelingEdgesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<EdgeApi> => {
    return apiMutator<EdgeApi>(getDataModelingEdgesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingEdgesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_edges/${id}/`
}

export const dataModelingEdgesUpdate = async (
    projectId: string,
    id: string,
    edgeApi?: NonReadonly<EdgeApi>,
    options?: RequestInit
): Promise<EdgeApi> => {
    return apiMutator<EdgeApi>(getDataModelingEdgesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(edgeApi),
    })
}

export const getDataModelingEdgesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_edges/${id}/`
}

export const dataModelingEdgesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedEdgeApi?: NonReadonly<PatchedEdgeApi>,
    options?: RequestInit
): Promise<EdgeApi> => {
    return apiMutator<EdgeApi>(getDataModelingEdgesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEdgeApi),
    })
}

export const getDataModelingEdgesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_edges/${id}/`
}

export const dataModelingEdgesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataModelingEdgesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDataModelingNodesListUrl = (projectId: string, params?: DataModelingNodesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_modeling_nodes/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_nodes/`
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

export const getDataModelingNodesRetrieveUrl = (
    projectId: string,
    id: string,
    params?: DataModelingNodesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_modeling_nodes/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_nodes/${id}/`
}

export const dataModelingNodesRetrieve = async (
    projectId: string,
    id: string,
    params?: DataModelingNodesRetrieveParams,
    options?: RequestInit
): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingNodesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/${id}/`
}

export const dataModelingNodesUpdate = async (
    projectId: string,
    id: string,
    nodeApi: NonReadonly<NodeApi>,
    options?: RequestInit
): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(nodeApi),
    })
}

export const getDataModelingNodesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/${id}/`
}

export const dataModelingNodesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedNodeApi?: NonReadonly<PatchedNodeApi>,
    options?: RequestInit
): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedNodeApi),
    })
}

export const getDataModelingNodesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/${id}/`
}

export const dataModelingNodesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataModelingNodesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDataModelingNodesMaterializeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/${id}/materialize/`
}

/**
 * Materialize just this single node.
 */
export const dataModelingNodesMaterializeCreate = async (
    projectId: string,
    id: string,
    nodeApi: NonReadonly<NodeApi>,
    options?: RequestInit
): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesMaterializeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(nodeApi),
    })
}

export const getDataModelingNodesResumeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/${id}/resume/`
}

/**
 * Resume a node suspended after repeated failed materializations.
 *
 * Scheduled runs skip a suspended node and its descendants, so it cannot succeed its way back
 * on its own. Resuming also gives it a fresh failure window rather than re-suspending on the
 * next failure.
 */
export const dataModelingNodesResumeCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<NodeResumeApi> => {
    return apiMutator<NodeResumeApi>(getDataModelingNodesResumeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getDataModelingNodesRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/${id}/run/`
}

/**
 * Run this node with its upstream dependencies or downstream dependents.
 */
export const dataModelingNodesRunCreate = async (
    projectId: string,
    id: string,
    nodeRunApi: NodeRunApi,
    options?: RequestInit
): Promise<NodeRunResponseApi> => {
    return apiMutator<NodeRunResponseApi>(getDataModelingNodesRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(nodeRunApi),
    })
}

export const getDataModelingNodesLineageRetrieveUrl = (
    projectId: string,
    params?: DataModelingNodesLineageRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_modeling_nodes/lineage/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_nodes/lineage/`
}

/**
 * Return the subgraph of nodes and edges reachable from a node (upstream + downstream).
 *
 * Accepts node_id, saved_query_id or metric_id, so a caller holding only the backing resource
 * (the SQL editor, the metric page) doesn't need to resolve the node itself.
 */
export const dataModelingNodesLineageRetrieve = async (
    projectId: string,
    params?: DataModelingNodesLineageRetrieveParams,
    options?: RequestInit
): Promise<LineageResponseApi> => {
    return apiMutator<LineageResponseApi>(getDataModelingNodesLineageRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingUsageListUrl = (projectId: string, params?: DataModelingUsageListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_modeling_usage/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_usage/`
}

export const dataModelingUsageList = async (
    projectId: string,
    params?: DataModelingUsageListParams,
    options?: RequestInit
): Promise<ModelUsageApi> => {
    return apiMutator<ModelUsageApi>(getDataModelingUsageListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
