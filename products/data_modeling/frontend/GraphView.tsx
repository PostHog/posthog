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
import { useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconCollapse, IconDatabase, IconExpand } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { IconArrowDown } from 'lib/lemon-ui/icons'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DataModelingNodeType } from '~/types'

import { REACT_FLOW_NODE_TYPES } from './Node'
import { dataModelingLogic, parseSearchTerm } from './dataModelingLogic'
import { CreateModelNodeType, ElkDirection, Node } from './types'

const FIT_VIEW_OPTIONS = {
    padding: 0.2,
    maxZoom: 1,
}

const NODE_TYPE_COLORS: Record<DataModelingNodeType, string> = {
    table: 'var(--muted)',
    view: 'var(--primary-3000)',
    matview: 'var(--success)',
}

const NODES_TO_SHOW: CreateModelNodeType[] = [
    {
        type: 'view',
        name: 'View',
        description: 'A virtual table based on a SQL query',
    },
    {
        type: 'matview',
        name: 'Materialized view',
        description: 'A persisted view with improved query performance',
    },
]

function NodeTypeButton({
    node,
    isActive,
    onClick,
}: {
    node: CreateModelNodeType
    isActive: boolean
    onClick: () => void
}): JSX.Element {
    const color = NODE_TYPE_COLORS[node.type]

    return (
        <div draggable>
            <LemonButton
                icon={
                    <span style={{ color }}>
                        <IconDatabase />
                    </span>
                }
                fullWidth
                active={isActive}
                onClick={onClick}
            >
                <div className="flex flex-col items-start flex-1">
                    <span>{node.name}</span>
                    {node.description && <span className="text-xs text-muted font-normal">{node.description}</span>}
                </div>
            </LemonButton>
        </div>
    )
}

export function NodeTypePanel(): JSX.Element {
    const { highlightedNodeType, layoutDirection } = useValues(dataModelingLogic)
    const { setHighlightedNodeType, setLayoutDirection, setSearchTerm } = useActions(dataModelingLogic)
    const [collapsed, setCollapsed] = useState(false)

    const handleNodeTypeClick = (type: DataModelingNodeType): void => {
        if (highlightedNodeType === type) {
            setHighlightedNodeType(null)
        } else {
            setHighlightedNodeType(type)
            setSearchTerm('')
        }
    }

    if (collapsed) {
        return (
            <div className="absolute right-1.5 bottom-1.5 z-10 bg-transparent p-2">
                <LemonButton
                    className="dark:bg-primary bg-white"
                    icon={<IconExpand />}
                    type="secondary"
                    size="small"
                    onClick={() => setCollapsed(false)}
                    tooltip="Expand panel"
                />
            </div>
        )
    }

    return (
        <div className="absolute right-4 top-4 bottom-4 w-64 bg-primary border rounded-lg shadow-xs overflow-hidden z-10">
            <div className="flex flex-col gap-1 p-4">
                <span className="flex gap-2 text-xs font-semibold items-center text-muted">Node types</span>
                {NODES_TO_SHOW.map((node, index) => (
                    <NodeTypeButton
                        key={`${node.type}-${index}`}
                        node={node}
                        isActive={highlightedNodeType === node.type}
                        onClick={() => handleNodeTypeClick(node.type)}
                    />
                ))}
            </div>
            <div className="absolute bottom-4 left-4 right-4 flex items-center justify-between">
                <LemonSegmentedButton
                    value={layoutDirection}
                    onChange={(value) => setLayoutDirection(value as ElkDirection)}
                    options={[
                        {
                            value: 'RIGHT',
                            icon: <IconArrowRight />,
                            tooltip: 'Left to right',
                        },
                        {
                            value: 'DOWN',
                            icon: <IconArrowDown />,
                            tooltip: 'Top to bottom',
                        },
                    ]}
                    size="small"
                />
                <LemonButton
                    className="dark:bg-primary bg-white"
                    icon={<IconCollapse />}
                    type="secondary"
                    size="small"
                    onClick={() => setCollapsed(true)}
                    tooltip="Collapse panel"
                />
            </div>
        </div>
    )
}

function GraphViewContent(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { enrichedNodes, enrichedEdges, highlightedNodeIds, debouncedSearchTerm, savedViewport } =
        useValues(dataModelingLogic)
    const { onEdgesChange, onNodesChange, setReactFlowInstance, setReactFlowWrapper } = useActions(dataModelingLogic)

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
            let matchingNodes: Node[]
            if (mode !== 'search') {
                const highlightedIds = highlightedNodeIds(baseName, mode)
                matchingNodes = enrichedNodes.filter((n: Node) => highlightedIds.has(n.id))
            } else {
                matchingNodes = enrichedNodes.filter((n: Node) =>
                    n.data.name.toLowerCase().includes(baseName.toLowerCase())
                )
            }
            if (matchingNodes.length > 0) {
                reactFlowInstance.fitView({
                    nodes: matchingNodes,
                    duration: 400,
                    maxZoom: 1,
                })
            }
        }
    }, [debouncedSearchTerm, enrichedNodes, reactFlowInstance, highlightedNodeIds])

    return (
        <div ref={reactFlowWrapper} className="relative w-full border rounded-lg overflow-hidden h-[calc(100vh-14rem)]">
            <ReactFlow<Node, Edge>
                fitView={!savedViewport}
                defaultViewport={savedViewport ?? undefined}
                nodes={enrichedNodes}
                edges={enrichedEdges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                nodeTypes={REACT_FLOW_NODE_TYPES as NodeTypes}
                nodesDraggable={false}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                fitViewOptions={FIT_VIEW_OPTIONS}
                proOptions={{ hideAttribution: true }}
                elevateNodesOnSelect={false}
                minZoom={0.25}
                maxZoom={1.5}
                onlyRenderVisibleElements
            >
                <Background gap={36} variant={BackgroundVariant.Dots} bgColor="var(--color-bg-primary)" />
                <Controls showInteractive={false} fitViewOptions={FIT_VIEW_OPTIONS} />
                <NodeTypePanel />
            </ReactFlow>
        </div>
    )
}

export function GraphView(): JSX.Element {
    return (
        <ReactFlowProvider>
            <GraphViewContent />
        </ReactFlowProvider>
    )
}
