import { useActions, useValues } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { DataModelingNode } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'

import { sqlEditorLogic } from '../../sqlEditorLogic'

export function UpstreamGraph({ tabId }: { tabId: string }): JSX.Element {
    const { upstream, editingView } = useValues(sqlEditorLogic({ tabId }))
    const { editView } = useActions(sqlEditorLogic({ tabId }))

    const nodes = upstream?.nodes ?? []
    const edges = upstream?.edges ?? []
    const currentNodeId = nodes.find((n) => n.saved_query_id && n.saved_query_id === editingView?.id)?.id

    const openInEditor = async (node: DataModelingNode): Promise<void> => {
        if (!node.saved_query_id) {
            return
        }
        try {
            const view = await api.dataWarehouseSavedQueries.get(node.saved_query_id)
            if (view?.query?.query) {
                editView(view.query.query, view)
            }
        } catch {
            lemonToast.error('Failed to load view details')
        }
    }

    return (
        <div className="h-[500px] border border-border rounded-md overflow-hidden">
            <LineageGraph
                nodes={nodes}
                edges={edges}
                currentNodeId={currentNodeId}
                variant="full"
                interactive
                showControls
                showMinimap
                emptyMessage="This query doesn't depend on any other tables or views"
                nodeCallbacks={(node) => ({
                    onEdit:
                        node.type !== 'table' && node.id !== currentNodeId ? () => void openInEditor(node) : undefined,
                })}
            />
        </div>
    )
}
