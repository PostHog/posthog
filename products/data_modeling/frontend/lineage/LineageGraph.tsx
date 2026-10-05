import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    ControlButton,
    Controls,
    FitViewOptions,
    MiniMap,
    Panel,
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
    useStore,
    type XYPosition,
} from '@xyflow/react'
import clsx from 'clsx'
import { useValues } from 'kea'
import { type KeyboardEvent, type MouseEvent, ReactNode, useEffect, useMemo, useRef } from 'react'

import { IconArchive, IconRefresh } from '@posthog/icons'

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
    nodesDraggable?: boolean
    nodePositions?: Record<string, XYPosition>
    onNodeDragStop?: (node: DataModelingNode, position: XYPosition) => void
    onResetNodePositions?: () => void
    fitViewOptions?: FitViewOptions
    focusNodeIds?: Set<string> | null
    searchFocusRequest?: { nodeId: string; requestId: number } | null
    showMinimap?: boolean
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
    /** Dedicated new-tab link shown on each node */
    nodeOpenUrl?: (node: DataModelingNode) => string
    /** Caller-specific chrome (legend, layout toggle) rendered over the canvas */
    panels?: ReactNode
}

function LineageGraphContent(props: LineageGraphProps): JSX.Element {
    const { fitView, setNodes, viewportInitialized } = useReactFlow()
    const nodesMeasured = useNodesMeasured()
    const { isDarkModeOn } = useValues(themeLogic)
    const { currentNodeId, nodeState, nodeCallbacks, onNodeClick, nodeOpenUrl, focusNodeIds, searchFocusRequest } =
        props
    const { layout } = useValues(
        lineageGraphLogic({
            nodes: props.loading ? EMPTY_NODES : props.nodes,
            edges: props.loading ? EMPTY_EDGES : props.edges,
            variant: props.variant ?? 'full',
            direction: props.direction ?? 'RIGHT',
        })
    )
    const fittedLayout = useRef<typeof layout>(null)
    const fittedFocus = useRef<{ focusNodeIds: Set<string>; layout: typeof layout } | null>(null)
    const fittedSearchRequest = useRef<{ requestId: number; layout: typeof layout } | null>(null)
    const lastNodeDrag = useRef<{ nodeId: string; stoppedAt: number } | null>(null)
    const resetRequested = useRef(false)

    // Decorating on every render would hand react-flow new node objects, which drops the sizes it
    // measured — so the fit below would keep waiting and the edges would keep being redrawn.
    const decoratedNodes = useMemo(
        () =>
            layout?.nodes.map((rfNode) => {
                const node = rfNode.data.node as DataModelingNode
                const callbacks = nodeCallbacks?.(node) ?? {
                    onClick: onNodeClick ? () => onNodeClick(node) : undefined,
                }
                const onClick = callbacks.onClick
                return {
                    ...rfNode,
                    position: props.nodePositions?.[node.id] ?? rfNode.position,
                    data: {
                        ...rfNode.data,
                        draggable: props.nodesDraggable,
                        openUrl: nodeOpenUrl?.(node),
                        state: { isCurrent: node.id === currentNodeId, ...nodeState?.(node) },
                        callbacks: {
                            ...callbacks,
                            onClick: onClick
                                ? (event: MouseEvent | KeyboardEvent) => {
                                      const lastDrag = lastNodeDrag.current
                                      const isDragClick =
                                          event.detail > 0 &&
                                          lastDrag?.nodeId === node.id &&
                                          Date.now() - lastDrag.stoppedAt <= 200
                                      if (!isDragClick) {
                                          onClick(event)
                                      }
                                  }
                                : undefined,
                        },
                    },
                }
            }) ?? [],
        [
            currentNodeId,
            layout,
            nodeCallbacks,
            nodeOpenUrl,
            nodeState,
            onNodeClick,
            props.nodePositions,
            props.nodesDraggable,
        ]
    )

    const resetPositionsApplied = useStore(
        (state) =>
            !resetRequested.current ||
            decoratedNodes.every((node) => {
                const renderedNode = state.nodeLookup.get(node.id)
                return renderedNode?.position.x === node.position.x && renderedNode.position.y === node.position.y
            })
    )

    useEffect(() => {
        setNodes((currentNodes) => {
            if (currentNodes === decoratedNodes) {
                return currentNodes
            }
            const currentNodesById = new Map(currentNodes.map((node) => [node.id, node]))
            return decoratedNodes.map((node) => {
                const currentNode = currentNodesById.get(node.id)
                const measuredNode = currentNode?.measured ? { ...node, measured: currentNode.measured } : node
                return currentNode?.dragging
                    ? { ...measuredNode, position: currentNode.position, dragging: true }
                    : measuredNode
            })
        })
    }, [decoratedNodes, setNodes])

    const resetLayout = (): void => {
        resetRequested.current = true
        props.onResetNodePositions?.()
    }

    useEffect(() => {
        if (!resetRequested.current || Object.keys(props.nodePositions ?? {}).length > 0 || !resetPositionsApplied) {
            return
        }
        resetRequested.current = false
        void fitView({ nodes: decoratedNodes, padding: props.fitViewOptions?.padding ?? 0.2, duration: 400 })
    }, [decoratedNodes, fitView, props.fitViewOptions?.padding, props.nodePositions, resetPositionsApplied])

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
            nodes: decoratedNodes,
            padding: props.fitViewOptions?.padding ?? 0.2,
            duration: 400,
        })
    }, [
        fitView,
        focusNodeIds,
        decoratedNodes,
        layout,
        nodesMeasured,
        props.fitViewOptions,
        props.loading,
        searchFocusRequest,
        viewportInitialized,
    ])

    useEffect(() => {
        if (!focusNodeIds) {
            fittedFocus.current = null
            return
        }
        if (!viewportInitialized || !nodesMeasured || !layout || props.loading) {
            return
        }
        if (fittedFocus.current?.focusNodeIds === focusNodeIds && fittedFocus.current.layout === layout) {
            return
        }
        // An empty focusNodeIds means the search was cleared, so fit the whole graph again rather
        // than leave the viewport where the last selector zoomed it.
        const nodes =
            focusNodeIds.size > 0 ? decoratedNodes.filter((node) => focusNodeIds.has(node.id)) : decoratedNodes
        if (nodes.length > 0) {
            fittedFocus.current = { focusNodeIds, layout }
            void fitView({
                nodes,
                padding: 0.2,
                duration: 400,
                maxZoom: focusNodeIds.size > 0 ? 2 : undefined,
            })
        }
    }, [decoratedNodes, fitView, viewportInitialized, nodesMeasured, focusNodeIds, layout, props.loading])

    useEffect(() => {
        if (!searchFocusRequest) {
            fittedSearchRequest.current = null
            return
        }
        if (!viewportInitialized || !nodesMeasured || !layout || props.loading) {
            return
        }
        if (
            fittedSearchRequest.current?.requestId === searchFocusRequest.requestId &&
            fittedSearchRequest.current.layout === layout
        ) {
            return
        }
        const node = decoratedNodes.find((renderedNode) => renderedNode.id === searchFocusRequest.nodeId)
        if (node) {
            fittedSearchRequest.current = { requestId: searchFocusRequest.requestId, layout }
            void fitView({ nodes: [node], padding: 0.2, duration: 400, maxZoom: 2 })
        }
    }, [decoratedNodes, fitView, viewportInitialized, nodesMeasured, searchFocusRequest, layout, props.loading])

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
            className={clsx('@container/lineage', props.className)}
            colorMode={isDarkModeOn ? 'dark' : 'light'}
            defaultNodes={decoratedNodes}
            edges={layout.edges}
            nodeTypes={LINEAGE_NODE_TYPES}
            nodesDraggable={props.nodesDraggable ?? false}
            onNodeDragStop={(_, node) => {
                lastNodeDrag.current = { nodeId: node.id, stoppedAt: Date.now() }
                props.onNodeDragStop?.(node.data.node as DataModelingNode, node.position)
            }}
            nodesConnectable={false}
            elementsSelectable={false}
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
            {props.showControls && (
                <Controls showInteractive={false} position="bottom-left">
                    {props.nodesDraggable && props.onResetNodePositions && (
                        <ControlButton
                            aria-label="Reset layout"
                            title="Reset layout"
                            onClick={resetLayout}
                            data-attr="models-lineage-reset-layout"
                        >
                            <IconRefresh aria-hidden="true" />
                        </ControlButton>
                    )}
                </Controls>
            )}
            {props.showMinimap && (
                <MiniMap
                    zoomable
                    pannable
                    position="bottom-right"
                    nodeStrokeWidth={2}
                    className="hidden border rounded shadow-sm @min-[48rem]/lineage:block"
                />
            )}
            {props.panels && <Panel position="top-right">{props.panels}</Panel>}
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
