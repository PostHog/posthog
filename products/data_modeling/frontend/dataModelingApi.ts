import { ApiConfig, PaginatedResponse } from 'lib/api'

import { DataModelingDAG, DataModelingEdge, DataModelingJob, DataModelingNode } from '~/types'

import {
    dataModelingJobsRecentRetrieve,
    dataModelingJobsRunningRetrieve,
} from 'products/data_warehouse/frontend/generated/api'

import {
    dataModelingDagsCreate,
    dataModelingDagsDestroy,
    dataModelingDagsList,
    dataModelingDagsPartialUpdate,
    dataModelingEdgesList,
    dataModelingNodesLineageRetrieve,
    dataModelingNodesList,
    dataModelingNodesMaterializeCreate,
    dataModelingNodesPartialUpdate,
    dataModelingNodesRetrieve,
    dataModelingNodesRunCreate,
} from './generated/api'

// nosemgrep: prefer-codegen-api
const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const generatedDataModelingDags = {
    async list(): Promise<PaginatedResponse<DataModelingDAG>> {
        return (await dataModelingDagsList(projectId())) as unknown as PaginatedResponse<DataModelingDAG>
    },
    async create(data: { name: string; description?: string; sync_frequency?: string }): Promise<DataModelingDAG> {
        return (await dataModelingDagsCreate(
            projectId(),
            data as Parameters<typeof dataModelingDagsCreate>[1]
        )) as unknown as DataModelingDAG
    },
    async update(
        dagId: string,
        data: Partial<Pick<DataModelingDAG, 'name' | 'description' | 'sync_frequency'>>
    ): Promise<DataModelingDAG> {
        return (await dataModelingDagsPartialUpdate(
            projectId(),
            dagId,
            data as Parameters<typeof dataModelingDagsPartialUpdate>[2]
        )) as unknown as DataModelingDAG
    },
    async delete(dagId: string): Promise<void> {
        await dataModelingDagsDestroy(projectId(), dagId)
    },
}

export const generatedDataModelingNodes = {
    async list(dagId?: string): Promise<PaginatedResponse<DataModelingNode>> {
        return (await dataModelingNodesList(projectId(), {
            dag: dagId,
        })) as unknown as PaginatedResponse<DataModelingNode>
    },
    async get(nodeId: string): Promise<DataModelingNode> {
        return (await dataModelingNodesRetrieve(projectId(), nodeId)) as unknown as DataModelingNode
    },
    async update(nodeId: string, data: Partial<Pick<DataModelingNode, 'description'>>): Promise<DataModelingNode> {
        return (await dataModelingNodesPartialUpdate(
            projectId(),
            nodeId,
            data as Parameters<typeof dataModelingNodesPartialUpdate>[2]
        )) as unknown as DataModelingNode
    },
    async run(nodeId: string, direction: 'upstream' | 'downstream'): Promise<{ node_ids: string[] }> {
        return (await dataModelingNodesRunCreate(projectId(), nodeId, {
            direction,
        } as unknown as Parameters<typeof dataModelingNodesRunCreate>[2])) as unknown as { node_ids: string[] }
    },
    async materialize(nodeId: string): Promise<void> {
        await dataModelingNodesMaterializeCreate(
            projectId(),
            nodeId,
            {} as Parameters<typeof dataModelingNodesMaterializeCreate>[2]
        )
    },
    async lineage({
        nodeId,
        savedQueryId,
    }: {
        nodeId?: string
        savedQueryId?: string
    }): Promise<{ nodes: DataModelingNode[]; edges: DataModelingEdge[] }> {
        return (await dataModelingNodesLineageRetrieve(projectId(), {
            node_id: nodeId,
            saved_query_id: savedQueryId,
        })) as unknown as { nodes: DataModelingNode[]; edges: DataModelingEdge[] }
    },
}

export const generatedDataModelingEdges = {
    async list(dagId?: string): Promise<PaginatedResponse<DataModelingEdge>> {
        return (await dataModelingEdgesList(projectId(), {
            dag: dagId,
        })) as unknown as PaginatedResponse<DataModelingEdge>
    },
}

export const generatedDataModelingJobs = {
    async listRunning(): Promise<DataModelingJob[]> {
        return (await dataModelingJobsRunningRetrieve(projectId())) as unknown as DataModelingJob[]
    },
    async listRecent(): Promise<DataModelingJob[]> {
        return (await dataModelingJobsRecentRetrieve(projectId())) as unknown as DataModelingJob[]
    },
}
