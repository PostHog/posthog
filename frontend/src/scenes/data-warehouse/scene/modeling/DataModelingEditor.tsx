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

import { dataModelingNodesLogic } from '../dataModelingNodesLogic'
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

    const { enrichedNodes, edges, nodesLoading } = useValues(dataModelingEditorLogic)
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
            const matchingNode = enrichedNodes.find((node) =>
                node.data.name.toLowerCase().includes(debouncedSearchTerm.toLowerCase())
            )
            if (matchingNode) {
                const targetX = matchingNode.position.x + NODE_WIDTH / 2
                const targetY = matchingNode.position.y + NODE_HEIGHT / 2
                const viewport = reactFlowInstance.getViewport()
                const wrapper = reactFlowWrapper.current
                if (wrapper) {
                    const currentCenterX = -viewport.x / viewport.zoom + wrapper.clientWidth / 2 / viewport.zoom
                    const currentCenterY = -viewport.y / viewport.zoom + wrapper.clientHeight / 2 / viewport.zoom
                    const distance = Math.sqrt((targetX - currentCenterX) ** 2 + (targetY - currentCenterY) ** 2)
                    // skips animation for long distances to avoid rendering too many nodes during pan
                    const duration = distance > 2560 ? 0 : 400
                    reactFlowInstance.setCenter(targetX, targetY, { duration, zoom: 1 })
                }
            }
        }
    }, [debouncedSearchTerm, enrichedNodes, reactFlowInstance])

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
