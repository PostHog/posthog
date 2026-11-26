import { useActions, useValues } from 'kea'

import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'

import type { DataModelingNode, DataModelingNodeType, DataWarehouseSavedQuery } from '~/types'

import { canEditNodeDescription } from './nodeDescriptionState'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { nodeTypeForDisplay } from './nodeTypeForDisplay'

export interface NodeDetailHeaderState {
    node: DataModelingNode | null
    nodeLoading: boolean
    savedQuery: DataWarehouseSavedQuery | null
    savedQueryError: boolean
    nodeType: DataModelingNodeType | undefined
    canEdit: boolean
    updateNodeDescription: (description: string) => void
}

export function useNodeDetailHeader(id: string): NodeDetailHeaderState {
    const {
        node,
        nodeLoading,
        savedQuery: initialSavedQuery,
        savedQueryError,
    } = useValues(nodeDetailSceneLogic({ id }))
    const { updateNodeDescription } = useActions(nodeDetailSceneLogic({ id }))
    const { savedQuery: currentSavedQuery } = useValues(
        materializationJobsLogic({
            viewId: node?.saved_query_id ?? '',
            kind: node?.type === 'endpoint' ? 'endpoint' : 'view',
        })
    )
    const savedQuery = currentSavedQuery ?? initialSavedQuery
    return {
        node,
        nodeLoading,
        savedQuery,
        savedQueryError,
        nodeType: nodeTypeForDisplay(node, savedQuery),
        canEdit: canEditNodeDescription(node, savedQuery),
        updateNodeDescription,
    }
}
