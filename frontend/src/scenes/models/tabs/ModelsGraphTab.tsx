import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonInput } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'

import { modelsGraphLogic } from '../modelsGraphLogic'
import { modelsSceneLogic } from '../modelsSceneLogic'

export function ModelsGraphTab(): JSX.Element {
    const { nodes, nodesLoading } = useValues(modelsSceneLogic)
    const { edges, edgesLoading, searchTerm, highlightedNodeIds } = useValues(modelsGraphLogic)
    const { setSearchTerm } = useActions(modelsGraphLogic)

    return (
        <div className="h-[calc(100vh-17rem)] min-h-[400px] w-full border rounded bg-bg-light overflow-hidden">
            <LineageGraph
                nodes={nodes}
                edges={edges}
                variant="canvas"
                interactive
                showControls
                showMinimap
                loading={nodesLoading || edgesLoading}
                emptyMessage="No models yet. Create a view to see it here."
                nodeState={(node) => ({
                    isHighlighted: highlightedNodeIds.has(node.id),
                    isRunning: node.last_run_status === 'Running',
                })}
                onNodeClick={(node) => router.actions.push(urls.nodeDetail(node.id))}
                panels={
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search models"
                        value={searchTerm}
                        onChange={setSearchTerm}
                        className="w-60 bg-bg-light"
                        data-attr="models-graph-search"
                    />
                }
            />
        </div>
    )
}
