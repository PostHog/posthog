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

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { DataModelingEditorPanel } from './DataModelingEditorPanel'
import { REACT_FLOW_NODE_TYPES } from './Nodes'
import { dataModelingEditorLogic } from './dataModelingEditorLogic'
import { ModelNode } from './types'

function DataModelingEditorContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { nodes, edges } = useValues(dataModelingEditorLogic)
    const {
        onEdgesChange,
        onNodesChange,
        setSelectedNodeId,
        setReactFlowInstance,
        onNodesDelete,
        setReactFlowWrapper,
    } = useActions(dataModelingEditorLogic)
    const reactFlowWrapper = useRef<HTMLDivElement>(null)
    const reactFlowInstance = useReactFlow()

    useEffect(() => {
        setReactFlowInstance(reactFlowInstance)
    }, [reactFlowInstance, setReactFlowInstance])

    useEffect(() => {
        setReactFlowWrapper(reactFlowWrapper)
    }, [setReactFlowWrapper])

    return (
        <div ref={reactFlowWrapper} className="w-full h-full">
            <ReactFlow<ModelNode, Edge>
                fitView
                nodes={[...nodes]}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodesDelete={onNodesDelete}
                onNodeClick={(_, node) => node.selectable && setSelectedNodeId(node.id)}
                nodeTypes={REACT_FLOW_NODE_TYPES as NodeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                onPaneClick={() => setSelectedNodeId(null)}
            >
                <Background gap={36} variant={BackgroundVariant.Dots} />
                <Controls showInteractive={false} />
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
