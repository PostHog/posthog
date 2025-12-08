import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    EdgeTypes,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { dataModelingNodesLogic } from '../dataModelingNodesLogic'
import { DataModelingEditorPanel } from './DataModelingEditorPanel'
import { REACT_FLOW_NODE_TYPES } from './Nodes'
import { REACT_FLOW_EDGE_TYPES } from './SmartEdge'
import { NODE_HEIGHT, NODE_WIDTH } from './constants'
import { dataModelingEditorLogic } from './dataModelingEditorLogic'
import { ModelNode } from './types'

const FIT_VIEW_OPTIONS = {
    padding: 0.2,
    maxZoom: 1,
}

function DataModelingEditorContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { nodes, edges, dropzoneNodes } = useValues(dataModelingEditorLogic)
    const {
        onEdgesChange,
        onNodesChange,
        setSelectedNodeId,
        setReactFlowInstance,
        onNodesDelete,
        onDragStart,
        onDragOver,
        onDrop,
        setReactFlowWrapper,
    } = useActions(dataModelingEditorLogic)
    const { searchTerm } = useValues(dataModelingNodesLogic)

    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()

    useEffect(() => {
        setReactFlowInstance(reactFlowInstance)
    }, [reactFlowInstance, setReactFlowInstance])

    useEffect(() => {
        setReactFlowWrapper(reactFlowWrapper)
    }, [setReactFlowWrapper])

    useEffect(() => {
        if (searchTerm.length > 0 && nodes.length > 0) {
            const matchingNode = nodes.find((node) => node.data.name.toLowerCase().includes(searchTerm.toLowerCase()))
            if (matchingNode) {
                const x = matchingNode.position.x + NODE_WIDTH / 2
                const y = matchingNode.position.y + NODE_HEIGHT / 2
                reactFlowInstance.setCenter(x, y, { duration: 300, zoom: 1 })
            }
        }
    }, [searchTerm, nodes, reactFlowInstance])

    return (
        <div ref={reactFlowWrapper} className="w-full h-full">
            <ReactFlow<ModelNode, Edge>
                fitView
                nodes={[...nodes, ...(dropzoneNodes as unknown as ModelNode[])]}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onDragStart={onDragStart}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onNodeClick={(_, node) => node.selectable && setSelectedNodeId(node.id)}
                nodeTypes={REACT_FLOW_NODE_TYPES as NodeTypes}
                edgeTypes={REACT_FLOW_EDGE_TYPES as EdgeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                onPaneClick={() => setSelectedNodeId(null)}
                fitViewOptions={FIT_VIEW_OPTIONS}
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
