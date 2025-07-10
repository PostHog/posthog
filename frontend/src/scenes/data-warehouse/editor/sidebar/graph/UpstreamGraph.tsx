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
import { IconArchive, IconTarget } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { LineageNode as LineageNodeType } from '~/types'

import { multitabEditorLogic } from '../../multitabEditorLogic'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

interface UpstreamGraphProps {
    codeEditorKey: string
}

interface LineageNodeProps {
    data: LineageNodeType & { isCurrentView?: boolean }
    edges: { source: string; target: string }[]
}

const MAT_VIEW_HEIGHT = 92
const TABLE_HEIGHT = 68

const NODE_WIDTH = 240

const MARKER_SIZE = 20

const NODE_SEP = 80
const RANK_SEP = 160

function LineageNode({ data, edges }: LineageNodeProps): JSX.Element {
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
        return 'highlight'
    }

    // Only show handles if there are edges to/from this node
    const hasIncoming = edges.some((edge) => edge.target === data.id)
    const hasOutgoing = edges.some((edge) => edge.source === data.id)

    // Dynamic height: mat views get extra height for last run time
    const isMatView = data.type === 'view' && !!data.last_run_at
    const nodeHeight = isMatView ? MAT_VIEW_HEIGHT : TABLE_HEIGHT

    return (
        <div
            className="bg-bg-light border border-border rounded-lg p-3 min-w-[240px] shadow-sm"
            style={{ minHeight: nodeHeight }}
        >
            {hasIncoming && <Handle type="target" position={Position.Left} className="w-2 h-2 bg-primary" />}

            <div className="flex items-center gap-2 mb-2">
                {data.isCurrentView && (
                    <Tooltip placement="top" title="This is the currently viewed query">
                        <IconTarget className="text-warning text-sm" />
                    </Tooltip>
                )}
                <Tooltip title={data.name} placement="top">
                    <span className="font-medium text-sm truncate max-w-[180px] block">{data.name}</span>
                </Tooltip>
            </div>

            <div className="flex items-center gap-2">
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
                <div className="text-xs text-muted mt-2">Last run: {humanFriendlyDetailedTime(data.last_run_at)}</div>
            )}

            {hasOutgoing && <Handle type="source" position={Position.Right} className="w-2 h-2 bg-primary" />}
        </div>
    )
}

const getNodeTypes = (edges: { source: string; target: string }[]): NodeTypes => ({
    lineageNode: (props) => <LineageNode {...props} edges={edges} />,
})

const getLayoutedElements = (
    nodes: LineageNodeType[],
    edges: { source: string; target: string }[],
    currentViewName?: string
): { nodes: Node[]; edges: Edge[] } => {
    const dagreGraph = new dagre.graphlib.Graph()
    dagreGraph.setDefaultEdgeLabel(() => ({}))
    dagreGraph.setGraph({ rankdir: 'LR', nodesep: NODE_SEP, ranksep: RANK_SEP })

    // Add nodes and edges to dagre and layout with dagre
    nodes.forEach((node) => {
        const isMatView = node.type === 'view' && !!node.last_run_at
        dagreGraph.setNode(node.id, { width: NODE_WIDTH, height: isMatView ? MAT_VIEW_HEIGHT : TABLE_HEIGHT })
    })
    edges.forEach((edge) => {
        dagreGraph.setEdge(edge.source, edge.target)
    })
    dagre.layout(dagreGraph)

    const layoutedNodes: Node[] = nodes.map((node) => {
        const nodeWithPosition = dagreGraph.node(node.id)
        const isMatView = node.type === 'view' && !!node.last_run_at
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
            width: NODE_WIDTH,
            height: isMatView ? MAT_VIEW_HEIGHT : TABLE_HEIGHT,
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
            width: MARKER_SIZE,
            height: MARKER_SIZE,
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
            <div
                data-attr="upstream-graph-empty-state"
                className="flex flex-col flex-1 rounded p-4 w-full items-center justify-center"
            >
                <IconArchive className="text-5xl mb-2 text-tertiary" />
                <h2 className="text-xl leading-tight">No tables or views found</h2>
                <p className="text-sm text-center text-balance text-tertiary">
                    This query doesn't depend on any other tables or views
                </p>
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
                nodeTypes={getNodeTypes(edges)}
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
