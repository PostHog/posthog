import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    Handle,
    MarkerType,
    Node,
    NodeTypes,
    Position,
    ReactFlow,
    ReactFlowProvider,
    MiniMap,
    useReactFlow,
} from '@xyflow/react'
import dagre from '@dagrejs/dagre'
import { IconTarget } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { LineageNode } from '~/types'

import { multitabEditorLogic } from '../multitabEditorLogic'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

interface UpstreamGraphProps {
    codeEditorKey: string
}

// Custom node component for lineage nodes
function LineageNodeComponent({ data }: { data: LineageNode & { isCurrentView?: boolean } }): JSX.Element {
    const getNodeType = (type: string, lastRunAt?: string): string => {
        if (type === 'view') {
            return lastRunAt ? 'Mat. View' : 'View'
        }
        return 'Table'
    }

    const getTagType = (type: string): LemonTagType => {
        if (type === 'view') {
            return 'primary'
        }
        return 'default'
    }

    return (
        <div className="bg-bg-light border border-border rounded-lg p-3 min-w-[200px] shadow-sm">
            <Handle type="target" position={Position.Left} className="w-2 h-2 bg-primary" />

            <div className="flex items-center gap-2 mb-2">
                {data.isCurrentView && (
                    <Tooltip placement="top" title="This is the currently viewed query">
                        <IconTarget className="text-warning text-sm" />
                    </Tooltip>
                )}
                <Tooltip title={data.name} placement="top">
                    <span className="font-medium text-sm truncate max-w-[160px] block" style={{ lineHeight: '1.2' }}>
                        {data.name}
                    </span>
                </Tooltip>
            </div>

            <div className="flex items-center gap-2 mb-2">
                <LemonTag type={getTagType(data.type)} size="small">
                    {getNodeType(data.type, data.last_run_at)}
                </LemonTag>
                {data.status && (
                    <LemonTag
                        type={data.status === 'Failed' ? 'danger' : data.status === 'Running' ? 'warning' : 'success'}
                        size="small"
                    >
                        {data.status}
                    </LemonTag>
                )}
            </div>

            {data.last_run_at && (
                <div className="text-xs text-muted">Last run: {humanFriendlyDetailedTime(data.last_run_at)}</div>
            )}

            <Handle type="source" position={Position.Right} className="w-2 h-2 bg-primary" />
        </div>
    )
}

// Node types for ReactFlow
const nodeTypes: NodeTypes = {
    lineageNode: LineageNodeComponent,
}

// Layout the graph using dagre
const getLayoutedElements = (
    nodes: LineageNode[],
    edges: { source: string; target: string }[],
    currentViewName?: string
): { nodes: Node[]; edges: Edge[] } => {
    const dagreGraph = new dagre.graphlib.Graph()
    dagreGraph.setDefaultEdgeLabel(() => ({}))
    dagreGraph.setGraph({ rankdir: 'LR', nodesep: 80, ranksep: 160 })

    // Add nodes and edges to dagre
    nodes.forEach((node) => {
        dagreGraph.setNode(node.id, { width: 240, height: 120 })
    })
    edges.forEach((edge) => {
        dagreGraph.setEdge(edge.source, edge.target)
    })

    // Calculate layout
    dagre.layout(dagreGraph)

    // Convert back to ReactFlow format
    const layoutedNodes: Node[] = nodes.map((node) => {
        const nodeWithPosition = dagreGraph.node(node.id)
        return {
            id: node.id,
            type: 'lineageNode',
            position: {
                x: nodeWithPosition.x - nodeWithPosition.width / 2,
                y: nodeWithPosition.y - nodeWithPosition.height / 2,
            },
            data: {
                ...node,
                isCurrentView: node.name === currentViewName,
            },
            width: 240,
            height: 120,
        }
    })

    const layoutedEdges: Edge[] = edges.map((edge, index) => ({
        id: `edge-${index}`,
        source: edge.source,
        target: edge.target,
        type: 'smoothstep',
        animated: false,
        markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 20,
            height: 20,
        },
    }))

    return { nodes: layoutedNodes, edges: layoutedEdges }
}

function UpstreamGraphContent({ codeEditorKey }: UpstreamGraphProps): JSX.Element {
    const { upstream, editingView } = useValues(multitabEditorLogic({ key: codeEditorKey }))
    const { fitView } = useReactFlow()
    const { isDarkModeOn } = useValues(themeLogic)

    const { nodes, edges } = useMemo(() => {
        if (!upstream || upstream.nodes.length === 0) {
            return { nodes: [], edges: [] }
        }

        return getLayoutedElements(upstream.nodes, upstream.edges, editingView?.name)
    }, [upstream, editingView?.name])

    // Fit view when nodes change
    useEffect(() => {
        if (nodes.length > 0) {
            setTimeout(() => fitView({ padding: 0.1 }), 100)
        }
    }, [nodes, fitView])

    if (!upstream || upstream.nodes.length === 0) {
        return (
            <div className="w-full h-full flex items-center justify-center text-muted">
                <div className="text-center">
                    <div className="text-lg mb-2">No upstream dependencies found</div>
                    <div className="text-sm">This query doesn't depend on any other tables or views</div>
                </div>
            </div>
        )
    }

    return (
        <div className="w-full h-full">
            <ReactFlow
                proOptions={{
                    hideAttribution: true,
                }}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.1 }}
                minZoom={0.1}
                maxZoom={2}
            >
                <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
                <Controls showInteractive={false} position="bottom-right" />
                <MiniMap zoomable pannable position="bottom-left" nodeStrokeWidth={2} />
            </ReactFlow>
        </div>
    )
}

export function UpstreamGraph({ codeEditorKey }: UpstreamGraphProps): JSX.Element {
    return (
        <div className="w-full h-full">
            <ReactFlowProvider>
                <UpstreamGraphContent codeEditorKey={codeEditorKey} />
            </ReactFlowProvider>
        </div>
    )
}
