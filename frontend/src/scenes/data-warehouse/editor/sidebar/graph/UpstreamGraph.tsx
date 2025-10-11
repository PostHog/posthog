import '@xyflow/react/dist/style.css'

import dagre from '@dagrejs/dagre'
import {
    Background,
    BackgroundVariant,
    Controls,
    Edge,
    Handle,
    MarkerType,
    MiniMap,
    Node,
    NodeTypes,
    Position,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'
import React, { useEffect, useMemo, useState } from 'react'

import { IconArchive, IconPencil, IconTarget } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { LineageNode as LineageNodeType } from '~/types'

import { dataWarehouseViewsLogic } from '../../../saved_queries/dataWarehouseViewsLogic'
import { multitabEditorLogic } from '../../multitabEditorLogic'

interface UpstreamGraphProps {
    tabId: string
}

interface LineageNodeProps {
    data: LineageNodeType & { isCurrentView?: boolean }
    edges: { source: string; target: string }[]
    tabId: string
}

const MAT_VIEW_HEIGHT = 92
const TABLE_HEIGHT = 68

const NODE_WIDTH = 300

const MARKER_SIZE = 20

const NODE_SEP = 80
const RANK_SEP = 160

const BRAND_YELLOW = '#f9bd2b'

function LineageNode({ data, edges, tabId }: LineageNodeProps): JSX.Element {
    const { editView } = useActions(multitabEditorLogic({ tabId }))
    const { dataWarehouseSavedQueries } = useValues(dataWarehouseViewsLogic)

    const getNodeType = (type: string, lastRunAt?: string): string => {
        if (type === 'view') {
            return lastRunAt ? 'Mat. view' : 'View'
        }
        return 'Table'
    }

    const getTagType = (type: string): LemonTagType => {
        return type === 'view' ? 'primary' : 'highlight'
    }

    const hasIncoming = edges.some((edge) => edge.target === data.id)
    const hasOutgoing = edges.some((edge) => edge.source === data.id)
    const isMatView = data.type === 'view' && !!data.last_run_at
    const nodeHeight = isMatView ? MAT_VIEW_HEIGHT : TABLE_HEIGHT

    const handleEditView = async (): Promise<void> => {
        if (data.type === 'view') {
            const view = dataWarehouseSavedQueries.find((v) => v.name === data.name)
            if (view?.query?.query) {
                editView(view.query.query, view)
            }
        }
    }

    return (
        <div
            className="bg-bg-light border border-border rounded-md p-3 min-w-[300px] shadow-sm"
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
                    <div className="flex items-center w-full justify-between">
                        <div className="font-medium text-sm truncate max-w-[240px] block">{data.name}</div>
                        {data.type === 'view' && !data.isCurrentView && (
                            <LemonButton
                                size="xxsmall"
                                type="secondary"
                                icon={<IconPencil />}
                                onClick={handleEditView}
                            />
                        )}
                    </div>
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

const getNodeTypes = (edges: { source: string; target: string }[], tabId: string): NodeTypes => ({
    lineageNode: (props) => <LineageNode {...props} tabId={tabId} edges={edges} />,
})

const getLayoutedElements = (
    nodes: LineageNodeType[],
    edges: { source: string; target: string }[],
    currentViewName?: string
): { nodes: Node[]; edges: Edge[] } => {
    const dagreGraph = new dagre.graphlib.Graph()
    dagreGraph.setDefaultEdgeLabel(() => ({}))
    dagreGraph.setGraph({ rankdir: 'LR', nodesep: NODE_SEP, ranksep: RANK_SEP })

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
        type: 'default',
        animated: false,
        markerEnd: {
            type: MarkerType.ArrowClosed,
            width: MARKER_SIZE,
            height: MARKER_SIZE,
            color: BRAND_YELLOW,
        },
    }))

    return { nodes: layoutedNodes, edges: layoutedEdges }
}

function UpstreamGraphContent({ tabId }: UpstreamGraphProps): JSX.Element {
    const { upstream, editingView } = useValues(multitabEditorLogic({ tabId }))
    const { fitView } = useReactFlow()
    const { isDarkModeOn } = useValues(themeLogic)

    const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
    const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null)

    const { nodes, edges } = useMemo(() => {
        if (!upstream || upstream.nodes.length === 0) {
            return { nodes: [], edges: [] }
        }

        return getLayoutedElements(upstream.nodes, upstream.edges, editingView?.name)
    }, [upstream, editingView?.name])

    const nodeTypes = useMemo(() => getNodeTypes(edges, tabId), [edges, tabId])

    const coloredEdges: Edge[] = edges.map((edge) => {
        const isHighlighted =
            edge.id === hoveredEdgeId || edge.source === hoveredNodeId || edge.target === hoveredNodeId

        return {
            ...edge,
            style: isHighlighted ? { stroke: BRAND_YELLOW } : undefined,
            markerEnd: {
                type: MarkerType.ArrowClosed,
                width: MARKER_SIZE,
                height: MARKER_SIZE,
                ...(isHighlighted ? { color: BRAND_YELLOW } : {}),
            },
        }
    })

    const onNodeMouseEnter = (_e: React.MouseEvent, node: Node): void => setHoveredNodeId(node.id)
    const onNodeMouseLeave = (): void => setHoveredNodeId(null)
    const onEdgeMouseEnter = (_e: React.MouseEvent, edge: Edge): void => setHoveredEdgeId(edge.id)
    const onEdgeMouseLeave = (): void => setHoveredEdgeId(null)

    // Fit view when nodes change
    useEffect(() => {
        let timeoutId: ReturnType<typeof setTimeout> | null = null
        if (nodes.length > 0) {
            timeoutId = setTimeout(() => fitView({ padding: 0.1 }), 100)
        }
        return () => {
            if (timeoutId) {
                clearTimeout(timeoutId)
            }
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
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                nodes={nodes}
                edges={coloredEdges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.1 }}
                minZoom={0.1}
                maxZoom={2}
                onNodeMouseEnter={onNodeMouseEnter}
                onNodeMouseLeave={onNodeMouseLeave}
                onEdgeMouseEnter={onEdgeMouseEnter}
                onEdgeMouseLeave={onEdgeMouseLeave}
            >
                <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
                <Controls showInteractive={false} position="bottom-right" />
                <MiniMap zoomable pannable position="bottom-left" nodeStrokeWidth={2} className="hidden lg:block" />
            </ReactFlow>
        </div>
    )
}

export function UpstreamGraph({ tabId }: UpstreamGraphProps): JSX.Element {
    return (
        <div className="h-[500px] border border-border rounded-md overflow-hidden">
            <ReactFlowProvider>
                <UpstreamGraphContent tabId={tabId} />
            </ReactFlowProvider>
        </div>
    )
}
