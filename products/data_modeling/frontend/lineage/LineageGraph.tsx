import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    FitViewOptions,
    MiniMap,
    Panel,
    PanelPosition,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
} from '@xyflow/react'
import { useValues } from 'kea'
import { ReactNode, useEffect, useMemo, useRef } from 'react'

import { IconArchive } from '@posthog/icons'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DataModelingEdge, DataModelingNode } from '~/types'

import { ElkDirection } from './autolayout'
import { LineageGraphLoading } from './LineageGraphLoading'
import { lineageGraphLogic } from './lineageGraphLogic'
import { LINEAGE_NODE_TYPES, LineageNodeCallbacks, LineageNodeState, LineageVariant } from './LineageNode'
import { useNodesMeasured } from './useNodesMeasured'

export type { LineageVariant, LineageNodeState, LineageNodeCallbacks } from './LineageNode'

const EMPTY_NODES: DataModelingNode[] = []
const EMPTY_EDGES: DataModelingEdge[] = []

export interface LineageGraphProps {
    nodes: DataModelingNode[]
    edges: DataModelingEdge[]
    /** Highlighted "you are here" node, rendered with a target marker + accent border */
    currentNodeId?: string
    variant?: LineageVariant
    direction?: ElkDirection
    /** Enable zoom/pan. Off by default for inline previews */
    interactive?: boolean
    fitViewOptions?: FitViewOptions
    focusNodeIds?: Set<string> | null
    searchFocusRequest?: { nodeId: string; requestId: number } | null
    showMinimap?: boolean
    minimapPosition?: PanelPosition
    showControls?: boolean
    className?: string
    loading?: boolean
    loadingCenter?: Pick<DataModelingNode, 'name' | 'type'>
    emptyMessage?: string
    /** Per-node visual state (running, dimmed, highlighted), computed by the caller */
    nodeState?: (node: DataModelingNode) => LineageNodeState
    /** Per-node affordances (click, run, edit), wired by the caller to its own logic */
    nodeCallbacks?: (node: DataModelingNode) => LineageNodeCallbacks
    /** Convenience click handler, used when nodeCallbacks is not provided */
    onNodeClick?: (node: DataModelingNode) => void
    /** Caller-specific chrome (legend, layout toggle) rendered over the canvas */
    panels?: ReactNode
    panelPosition?: PanelPosition
}

function LineageGraphContent(props: LineageGraphProps): JSX.Element {
    const { fitView, viewportInitialized } = useReactFlow()
    const nodesMeasured = useNodesMeasured()
    const { isDarkModeOn } = useValues(themeLogic)
    const { currentNodeId, nodeState, nodeCallbacks, onNodeClick, focusNodeIds, searchFocusRequest } = props
    const { layout } = useValues(
        lineageGraphLogic({
            nodes: props.loading ? EMPTY_NODES : props.nodes,
            edges: props.loading ? EMPTY_EDGES : props.edges,
            variant: props.variant ?? 'full',
            direction: props.direction ?? 'RIGHT',
        })
    )
    const fittedLayout = useRef<typeof layout>(null)

    // Decorating on every render would hand react-flow new node objects, which drops the sizes it
    // measured — so the fit below would keep waiting and the edges would keep being redrawn.
    const decoratedNodes = useMemo(
        () =>
            layout?.nodes.map((rfNode) => {
                const node = rfNode.data.node as DataModelingNode
                return {
                    ...rfNode,
                    data: {
                        ...rfNode.data,
                        state: { isCurrent: node.id === currentNodeId, ...nodeState?.(node) },
                        callbacks: nodeCallbacks?.(node) ?? {
                            onClick: onNodeClick ? () => onNodeClick(node) : undefined,
                        },
                    },
                }
            }) ?? [],
        [currentNodeId, layout, nodeCallbacks, nodeState, onNodeClick]
    )

    useEffect(() => {
        if (!viewportInitialized || !nodesMeasured || !layout || props.loading || fittedLayout.current === layout) {
            return
        }
        fittedLayout.current = layout
        if ((focusNodeIds !== null && focusNodeIds !== undefined) || searchFocusRequest) {
            return
        }
        void fitView({
            ...props.fitViewOptions,
            nodes: layout.nodes,
            padding: props.fitViewOptions?.padding ?? 0.2,
            duration: 400,
        })
    }, [
        fitView,
        focusNodeIds,
        layout,
        nodesMeasured,
        props.fitViewOptions,
        props.loading,
        searchFocusRequest,
        viewportInitialized,
    ])

    useEffect(() => {
        if (!viewportInitialized || !focusNodeIds || !layout || props.loading) {
            return
        }
        // An empty focusNodeIds means the search was cleared, so fit the whole graph again rather
        // than leave the viewport where the last selector zoomed it.
        const nodes = focusNodeIds.size > 0 ? layout.nodes.filter((node) => focusNodeIds.has(node.id)) : layout.nodes
        if (nodes.length > 0) {
            void fitView({
                nodes,
                padding: 0.2,
                duration: 400,
                maxZoom: focusNodeIds.size > 0 ? 2 : undefined,
            })
        }
    }, [fitView, viewportInitialized, focusNodeIds, layout, props.loading])

    useEffect(() => {
        if (!viewportInitialized || !searchFocusRequest || !layout || props.loading) {
            return
        }
        const node = layout.nodes.find((layoutNode) => layoutNode.id === searchFocusRequest.nodeId)
        if (node) {
            void fitView({ nodes: [node], padding: 0.2, duration: 400, maxZoom: 2 })
        }
    }, [fitView, viewportInitialized, searchFocusRequest, layout, props.loading])

    if (props.loading || !layout) {
        const center = props.loadingCenter ?? props.nodes.find((node) => node.id === currentNodeId)
        return (
            <LineageGraphLoading
                center={center}
                direction={props.direction ?? 'RIGHT'}
                fitViewOptions={props.fitViewOptions}
                variant={props.variant ?? 'full'}
            />
        )
    }

    return (
        <ReactFlow
            colorMode={isDarkModeOn ? 'dark' : 'light'}
            nodes={decoratedNodes}
            edges={layout.edges}
            nodeTypes={LINEAGE_NODE_TYPES}
            nodesDraggable={false}
            nodesConnectable={false}
            // The card inside each node is the focus target and carries the key handler. A focusable
            // wrapper would add a second tab stop per node that only selects and never navigates.
            nodesFocusable={false}
            minZoom={0.1}
            maxZoom={2}
            zoomOnScroll={props.interactive ?? false}
            panOnScroll={props.interactive ?? false}
            zoomOnPinch={props.interactive ?? false}
            zoomOnDoubleClick={props.interactive ?? false}
            proOptions={{ hideAttribution: true }}
        >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
            {props.showControls && <Controls showInteractive={false} position="bottom-right" />}
            {props.showMinimap && (
                <MiniMap
                    zoomable
                    pannable
                    position={props.minimapPosition ?? 'bottom-left'}
                    nodeStrokeWidth={2}
                    className="hidden lg:block border rounded shadow-sm"
                />
            )}
            {props.panels && <Panel position={props.panelPosition ?? 'top-right'}>{props.panels}</Panel>}
        </ReactFlow>
    )
}

export function LineageGraph(props: LineageGraphProps): JSX.Element {
    if (!props.loading && props.nodes.length === 0) {
        return (
            <div className="flex flex-col w-full h-full items-center justify-center p-4">
                <IconArchive className="text-5xl mb-2 text-tertiary" />
                <p className="text-sm text-center text-balance text-tertiary">
                    {props.emptyMessage ?? 'No tables or views found'}
                </p>
            </div>
        )
    }
    return (
        <ReactFlowProvider>
            <LineageGraphContent {...props} />
        </ReactFlowProvider>
    )
}
