import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { dataModelingNodesLogic, parseSearchTerm } from '../dataModelingNodesLogic'
import { DataModelingEditorPanel } from './DataModelingEditorPanel'
import { REACT_FLOW_NODE_TYPES } from './Nodes'
import { NODE_HEIGHT, NODE_WIDTH } from './constants'
import { dataModelingEditorLogic } from './dataModelingEditorLogic'
import { ModelNode } from './types'

const FIT_VIEW_OPTIONS = {
    padding: 0.2,
    maxZoom: 1,
}

function DataModelingEditorContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { enrichedNodes, edges, nodesLoading, highlightedNodeIds } = useValues(dataModelingEditorLogic)
    const {
        onEdgesChange,
        onNodesChange,
        setSelectedNodeId,
        setReactFlowInstance,
        onNodesDelete,
        setReactFlowWrapper,
    } = useActions(dataModelingEditorLogic)
    const { debouncedSearchTerm } = useValues(dataModelingNodesLogic)

    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()

    useEffect(() => {
        setReactFlowInstance(reactFlowInstance)
    }, [reactFlowInstance, setReactFlowInstance])

    useEffect(() => {
        setReactFlowWrapper(reactFlowWrapper)
    }, [setReactFlowWrapper])

    useEffect(() => {
        if (debouncedSearchTerm.length > 0 && enrichedNodes.length > 0) {
            const { baseName, mode } = parseSearchTerm(debouncedSearchTerm)
            let matchingNodes: ModelNode[]
            if (mode !== 'search') {
                const highlightedIds = highlightedNodeIds(baseName, mode)
                matchingNodes = enrichedNodes.filter((n) => highlightedIds.has(n.id))
            } else {
                matchingNodes = enrichedNodes.filter((n) => n.data.name.toLowerCase().includes(baseName.toLowerCase()))
            }
            if (matchingNodes.length > 0) {
                const centroidX =
                    matchingNodes.reduce((acc, node) => acc + node.position.x + NODE_WIDTH / 2, 0) /
                    matchingNodes.length
                const centroidY =
                    matchingNodes.reduce((acc, node) => acc + node.position.y + NODE_HEIGHT / 2, 0) /
                    matchingNodes.length
                const viewport = reactFlowInstance.getViewport()
                const wrapper = reactFlowWrapper.current
                if (wrapper) {
                    const currentCenterX = -viewport.x / viewport.zoom + wrapper.clientWidth / 2 / viewport.zoom
                    const currentCenterY = -viewport.y / viewport.zoom + wrapper.clientHeight / 2 / viewport.zoom
                    const distance = Math.sqrt((centroidX - currentCenterX) ** 2 + (centroidY - currentCenterY) ** 2)
                    // skips animation for long distances to avoid rendering too many nodes during pan
                    const duration = distance > 2560 ? 0 : 400
                    reactFlowInstance.setCenter(centroidX, centroidY, { duration, zoom: 1 })
                }
            }
        }
    }, [debouncedSearchTerm, enrichedNodes, reactFlowInstance, highlightedNodeIds])

    return (
        <div ref={reactFlowWrapper} className="relative w-full h-full">
            {nodesLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-bg-light/50 z-50">
                    <Spinner className="text-4xl" />
                </div>
            )}
            <ReactFlow<ModelNode, Edge>
                fitView
                nodes={enrichedNodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onNodeClick={(_, node) => node.selectable && setSelectedNodeId(node.id)}
                nodeTypes={REACT_FLOW_NODE_TYPES as NodeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                onPaneClick={() => setSelectedNodeId(null)}
                fitViewOptions={FIT_VIEW_OPTIONS}
                proOptions={{ hideAttribution: true }}
                elevateNodesOnSelect={false}
                minZoom={0.25}
                maxZoom={1.5}
                onlyRenderVisibleElements
            >
                <Background gap={36} variant={BackgroundVariant.Dots} />
                <Controls showInteractive={false} fitViewOptions={FIT_VIEW_OPTIONS} />
                <DataModelingEditorPanel />
            </ReactFlow>
        </div>
    )
}

export function DataModelingEditor(): JSX.Element {
    return (
        <ReactFlowProvider>
            <DataModelingEditorContent />
        </ReactFlowProvider>
    )
}
