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
    DagApi,
    DataModelingDagsListParams,
    DataModelingEdgesListParams,
    DataModelingNodesLineageRetrieveParams,
    DataModelingNodesListParams,
    EdgeApi,
    NodeApi,
    PaginatedDAGListApi,
    PaginatedEdgeListApi,
    PaginatedNodeListApi,
    PatchedDAGApi,
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

export const getDataModelingDagsListUrl = (projectId: string, params?: DataModelingDagsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_modeling_dags/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_modeling_dags/`
}

export const dataModelingDagsList = async (
    projectId: string,
    params?: DataModelingDagsListParams,
    options?: RequestInit
): Promise<PaginatedDAGListApi> => {
    return apiMutator<PaginatedDAGListApi>(getDataModelingDagsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingDagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_modeling_dags/`
}

export const dataModelingDagsCreate = async (
    projectId: string,
    dagApi: NonReadonly<DagApi>,
    options?: RequestInit
): Promise<DagApi> => {
    return apiMutator<DagApi>(getDataModelingDagsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dagApi),
    })
}

export const getDataModelingDagsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_dags/${id}/`
}

export const dataModelingDagsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DagApi> => {
    return apiMutator<DagApi>(getDataModelingDagsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingDagsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_dags/${id}/`
}

export const dataModelingDagsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDAGApi?: NonReadonly<PatchedDAGApi>,
    options?: RequestInit
): Promise<DagApi> => {
    return apiMutator<DagApi>(getDataModelingDagsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDAGApi),
    })
}

export const getDataModelingDagsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_dags/${id}/`
}

export const dataModelingDagsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataModelingDagsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedEdgeListApi> => {
    return apiMutator<PaginatedEdgeListApi>(getDataModelingEdgesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataModelingEdgesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_modeling_edges/`
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
    edgeApi: NonReadonly<EdgeApi>,
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

export const getDataModelingNodesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/`
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

export const getDataModelingNodesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/${id}/`
}

export const dataModelingNodesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesRetrieveUrl(projectId, id), {
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

export const getDataModelingNodesRunCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/${id}/run/`
}

/**
 * Run this node and its upstream or downstream dependencies.
 *
 * Request body:
 *     direction: "upstream" | "downstream" (required)
 *         - "upstream": Run all ancestors of this node, plus this node
 *         - "downstream": Run this node and all its descendants
 */
export const dataModelingNodesRunCreate = async (
    projectId: string,
    id: string,
    nodeApi: NonReadonly<NodeApi>,
    options?: RequestInit
): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesRunCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(nodeApi),
    })
}

export const getDataModelingNodesDagIdsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_modeling_nodes/dag_ids/`
}

/**
 * Get all distinct DAGs for the team.
 */
export const dataModelingNodesDagIdsRetrieve = async (projectId: string, options?: RequestInit): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesDagIdsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
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
 * Accepts either node_id or saved_query_id, so a caller holding only a saved query (the SQL
 * editor) doesn't need to resolve the node itself.
 */
export const dataModelingNodesLineageRetrieve = async (
    projectId: string,
    params?: DataModelingNodesLineageRetrieveParams,
    options?: RequestInit
): Promise<NodeApi> => {
    return apiMutator<NodeApi>(getDataModelingNodesLineageRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
