import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
    applyNodeChanges,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { CatalogGraphNode } from './CatalogGraphNode'
import { catalogGraphSceneLogic } from './catalogGraphSceneLogic'
import { CatalogGraphSidePanel } from './CatalogGraphSidePanel'
import { CatalogPageTabs } from './CatalogPageTabs'

const FIT_VIEW_OPTIONS = { padding: 0.15 }

const NODE_TYPES: NodeTypes = {
    catalogNode: CatalogGraphNode as any,
}

export const scene: SceneExport = {
    component: CatalogGraphScene,
    logic: catalogGraphSceneLogic,
    productKey: ProductKey.CATALOG,
}

export function CatalogGraphScene(): JSX.Element {
    return (
        <ReactFlowProvider>
            <CatalogGraphSceneContent />
        </ReactFlowProvider>
    )
}

function CatalogGraphSceneContent(): JSX.Element {
    const { graph, graphLoading, reactFlowNodes, reactFlowEdges } = useValues(catalogGraphSceneLogic)
    const { setNodes, setSelectedNodeId } = useActions(catalogGraphSceneLogic)

    if (graphLoading && !graph) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-64" />
                <LemonSkeleton className="h-96 w-full" />
            </SceneContent>
        )
    }

    if (!graph || graph.nodes.length === 0) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Catalog"
                    description="Tables, saved queries, and system tables tracked by the semantic layer."
                    resourceType={{ type: 'data_warehouse' }}
                />
                <CatalogPageTabs activeTab="graph" />
                <div className="text-secondary text-sm border rounded p-6 text-center">
                    No catalog nodes yet. Run the traversal workflow to populate the graph.
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Catalog"
                description={`${graph.nodes.length} nodes · ${graph.relationships.length} relationships`}
                resourceType={{ type: 'data_warehouse' }}
            />
            <CatalogPageTabs activeTab="graph" />
            <div className="relative border rounded" style={{ height: 'calc(100vh - 280px)', minHeight: 480 }}>
                <ReactFlow
                    nodes={reactFlowNodes}
                    edges={reactFlowEdges}
                    nodeTypes={NODE_TYPES}
                    onNodesChange={(changes) => setNodes(applyNodeChanges(changes, reactFlowNodes))}
                    onNodeClick={(_, node) => setSelectedNodeId(node.id)}
                    onPaneClick={() => setSelectedNodeId(null)}
                    fitView
                    fitViewOptions={FIT_VIEW_OPTIONS}
                    proOptions={{ hideAttribution: true }}
                >
                    <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
                    <Controls showInteractive={false} />
                </ReactFlow>
                <CatalogGraphSidePanel />
            </div>
        </SceneContent>
    )
}
