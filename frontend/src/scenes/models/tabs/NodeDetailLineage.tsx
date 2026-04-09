import '@xyflow/react/dist/style.css'

import {
    Background,
    Controls,
    Handle,
    MarkerType,
    Panel,
    Position,
    ReactFlow,
    ReactFlowProvider,
    type Edge as ReactFlowEdge,
    type Node as ReactFlowNode,
} from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type ComponentType, useCallback, useEffect, useMemo, useState } from 'react'

import { IconActivity, IconClockRewind, IconExternal } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { IconFullScreen } from 'lib/lemon-ui/icons'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { getFormattedNodes } from 'scenes/data-warehouse/scene/modeling/autolayout'
import { syncIntervalToShorthand } from 'scenes/data-warehouse/utils'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNodeType, DataModelingSyncInterval } from '~/types'

import { NODE_TYPE_TAG_SETTINGS } from '../nodeDetailConstants'
import { LineageGraphData, nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

// Shared node data used by both compact and fullscreen nodes
interface LineageNodeData extends Record<string, unknown> {
    nodeId: string
    name: string
    nodeType: DataModelingNodeType
    isCurrent: boolean
    lastJobStatus?: DataModelingJobStatus
    lastRunAt?: string
    syncInterval?: DataModelingSyncInterval
    upstreamCount: number
    downstreamCount: number
    /** The scene-level node ID, used to key nodeDetailSceneLogic */
    sceneId: string
}

// --- Shared sub-components ---

function NodeTypeTag({ nodeType }: { nodeType: DataModelingNodeType }): JSX.Element {
    const tagSettings = NODE_TYPE_TAG_SETTINGS[nodeType]
    return (
        <span
            className="text-[10px] lowercase tracking-wide px-1 rounded border-1"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                color: tagSettings.color,
                backgroundColor: `color-mix(in srgb, ${tagSettings.color} 20%, transparent)`,
                borderColor: `color-mix(in srgb, ${tagSettings.color} 80%, transparent)`,
            }}
        >
            {tagSettings.label}
        </span>
    )
}

function StatusDot({ status }: { status?: DataModelingJobStatus }): JSX.Element {
    return (
        <Tooltip title={status ?? 'Not run yet'}>
            <div
                className={clsx(
                    'rounded-full w-3 h-3 border-1 border-primary',
                    status === 'Completed' && 'bg-success',
                    status === 'Running' && 'bg-warning',
                    status === 'Failed' && 'bg-danger',
                    status === 'Cancelled' && 'bg-warning',
                    !status && 'bg-surface-primary'
                )}
            />
        </Tooltip>
    )
}

function NodeHandles({ nodeId }: { nodeId: string }): JSX.Element {
    return (
        <>
            <Handle
                id={`target_${nodeId}`}
                type="target"
                position={Position.Left}
                className="opacity-0"
                isConnectable={false}
            />
            <Handle
                id={`source_${nodeId}`}
                type="source"
                position={Position.Right}
                className="opacity-0"
                isConnectable={false}
            />
        </>
    )
}

// --- Compact node (used in inline partial lineage) ---

function LineageNodeCompact({ data }: { data: LineageNodeData }): JSX.Element {
    const tagSettings = NODE_TYPE_TAG_SETTINGS[data.nodeType]
    const handleClick = useCallback(() => {
        if (!data.isCurrent) {
            router.actions.push(urls.nodeDetail(data.nodeId))
        }
    }, [data.nodeId, data.isCurrent])

    return (
        <div
            className="px-3 py-2 bg-bg-light border rounded-lg cursor-pointer min-w-[140px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                borderColor: data.isCurrent ? tagSettings.color : 'var(--border)',
                borderWidth: data.isCurrent ? 2 : 1,
            }}
            onClick={handleClick}
        >
            <NodeHandles nodeId={data.nodeId} />
            <div className="flex items-center justify-between gap-2">
                <NodeTypeTag nodeType={data.nodeType} />
                {(data.nodeType === 'matview' || data.nodeType === 'endpoint') && (
                    <StatusDot status={data.lastJobStatus} />
                )}
            </div>
            <div className="text-sm font-medium truncate mt-1">{data.name}</div>
        </div>
    )
}

// --- Fullscreen node (self-contained with metadata) ---

function FullscreenLineageNode({ data }: { data: LineageNodeData }): JSX.Element {
    const tagSettings = NODE_TYPE_TAG_SETTINGS[data.nodeType]
    const { closeLineageModal } = useActions(nodeDetailSceneLogic({ id: data.sceneId }))
    const handleClick = useCallback(() => {
        if (!data.isCurrent) {
            closeLineageModal()
            router.actions.push(urls.nodeDetail(data.nodeId))
        }
    }, [data.nodeId, data.isCurrent, closeLineageModal])

    const showMetadata = data.nodeType === 'matview' || data.nodeType === 'endpoint'

    return (
        <div
            className={clsx(
                'relative rounded-lg border bg-bg-light cursor-pointer min-w-[200px]',
                data.isCurrent && 'border-2'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                borderColor: data.isCurrent ? tagSettings.color : 'var(--border)',
            }}
            onClick={handleClick}
        >
            <NodeHandles nodeId={data.nodeId} />
            <div className="px-3 pt-3">
                <NodeTypeTag nodeType={data.nodeType} />
                <div className="text-sm font-medium truncate py-2">{data.name}</div>
            </div>
            {showMetadata && (
                <div className="flex items-center bg-primary dark:bg-primary/60 rounded-b-lg px-2.5 py-1.5 justify-between">
                    <div className="flex gap-1 text-[10px] items-center">
                        <IconClockRewind className="scale-x-[-1]" />
                        {syncIntervalToShorthand(data.syncInterval)}
                        <IconActivity />
                        {data.lastRunAt ? (
                            <TZLabel
                                className="text-[10px]"
                                time={data.lastRunAt}
                                formatDate="MMM DD, YYYY"
                                formatTime="HH:mm"
                                showPopover={false}
                            />
                        ) : (
                            <span>Never</span>
                        )}
                    </div>
                    <StatusDot status={data.lastJobStatus} />
                </div>
            )}
        </div>
    )
}

// --- Node type registrations ---

const compactNodeTypes = { lineage: LineageNodeCompact }
const fullscreenNodeTypes = { lineage: FullscreenLineageNode }

// --- Layout ---

interface LayoutResult {
    nodes: ReactFlowNode<LineageNodeData>[]
    edges: ReactFlowEdge[]
}

interface BuildLayoutOptions {
    /** Override lastJobStatus for the current node (derived from materialization jobs) */
    currentNodeStatus?: string
    /** Override lastRunAt for the current node (derived from materialization jobs) */
    currentNodeLastRunAt?: string
    /** Node dimensions for ELK layout — should match actual rendered size */
    nodeWidth?: number
    nodeHeight?: number
}

const COMPACT_NODE_WIDTH = 160
const COMPACT_NODE_HEIGHT = 55
const FULLSCREEN_NODE_WIDTH = 200
const FULLSCREEN_NODE_HEIGHT = 90

/** Convert LineageGraphData (from kea) into laid-out ReactFlow nodes + edges */
async function buildLineageLayout(data: LineageGraphData, options?: BuildLayoutOptions): Promise<LayoutResult> {
    const nodeWidth = options?.nodeWidth ?? COMPACT_NODE_WIDTH
    const nodeHeight = options?.nodeHeight ?? COMPACT_NODE_HEIGHT

    const rfNodes: ReactFlowNode<LineageNodeData>[] = data.nodes.map((n) => {
        const isCurrent = n.id === data.currentNodeId
        return {
            id: n.id,
            type: 'lineage',
            position: { x: 0, y: 0 },
            width: nodeWidth,
            height: nodeHeight,
            data: {
                name: n.name,
                nodeType: n.type,
                isCurrent,
                nodeId: n.id,
                sceneId: data.currentNodeId,
                lastJobStatus:
                    isCurrent && options?.currentNodeStatus
                        ? (options.currentNodeStatus as DataModelingJobStatus)
                        : n.last_run_status,
                lastRunAt: isCurrent && options?.currentNodeLastRunAt ? options.currentNodeLastRunAt : n.last_run_at,
                syncInterval: n.sync_interval,
                upstreamCount: n.upstream_count,
                downstreamCount: n.downstream_count,
                // handles needed by getFormattedNodes for ELK port layout
                handles: [
                    {
                        id: `target_${n.id}`,
                        type: 'target' as const,
                        position: Position.Left,
                    },
                    {
                        id: `source_${n.id}`,
                        type: 'source' as const,
                        position: Position.Right,
                    },
                ],
            },
        }
    })

    const rfEdges: ReactFlowEdge[] = data.edges.map((e) => ({
        id: e.id,
        source: e.source_id,
        target: e.target_id,
        sourceHandle: `source_${e.source_id}`,
        targetHandle: `target_${e.target_id}`,
        markerEnd: { type: MarkerType.ArrowClosed, width: 20, height: 20 },
    }))

    // Use ELK layout (same as the full DAG view)
    const laidOutNodes = await getFormattedNodes(rfNodes as any, rfEdges, 'RIGHT')

    return {
        nodes: laidOutNodes as unknown as ReactFlowNode<LineageNodeData>[],
        edges: rfEdges,
    }
}

// --- Graph content ---

function LineageGraphContent({
    layout,
    interactive,
    nodeTypes,
    onFullscreen,
}: {
    layout: LayoutResult
    interactive?: boolean
    nodeTypes: Record<string, ComponentType<any>>
    onFullscreen?: () => void
}): JSX.Element {
    return (
        <ReactFlow
            nodes={layout.nodes}
            edges={layout.edges}
            nodeTypes={nodeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            fitView
            minZoom={0.3}
            maxZoom={1.5}
            zoomOnScroll={interactive ?? false}
            panOnScroll={interactive ?? false}
            zoomOnPinch={interactive ?? false}
            zoomOnDoubleClick={interactive ?? false}
        >
            <Background />
            {interactive && <Controls showInteractive={false} />}
            {onFullscreen && (
                <Panel position="bottom-left">
                    <div className="flex flex-col gap-1">
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={urls.dataOps('modeling')}
                            tooltip="Open full DAG view"
                        >
                            <IconExternal />
                        </LemonButton>
                        <LemonButton type="secondary" size="small" onClick={onFullscreen} tooltip="Fullscreen">
                            <IconFullScreen />
                        </LemonButton>
                    </div>
                </Panel>
            )}
        </ReactFlow>
    )
}

// --- Main export ---

export function NodeDetailLineage({ id }: { id: string }): JSX.Element | null {
    const { lineageGraph, lineageGraphLoading, effectiveLastRunAt, effectiveLastRunStatus, lineageModalOpen } =
        useValues(nodeDetailSceneLogic({ id }))
    const { openLineageModal, closeLineageModal } = useActions(nodeDetailSceneLogic({ id }))
    const [compactLayout, setCompactLayout] = useState<LayoutResult | null>(null)
    const [fullscreenLayout, setFullscreenLayout] = useState<LayoutResult | null>(null)

    const overrides = useMemo(
        () => ({
            currentNodeStatus: effectiveLastRunStatus ?? undefined,
            currentNodeLastRunAt: effectiveLastRunAt ?? undefined,
        }),
        [effectiveLastRunStatus, effectiveLastRunAt]
    )

    // Run ELK layout when lineageGraph data or derived status changes
    useEffect(() => {
        if (!lineageGraph || lineageGraph.nodes.length <= 1) {
            setCompactLayout(null)
            setFullscreenLayout(null)
            return
        }
        let cancelled = false
        const compactOpts = {
            ...overrides,
            nodeWidth: COMPACT_NODE_WIDTH,
            nodeHeight: COMPACT_NODE_HEIGHT,
        }
        const fullscreenOpts = {
            ...overrides,
            nodeWidth: FULLSCREEN_NODE_WIDTH,
            nodeHeight: FULLSCREEN_NODE_HEIGHT,
        }

        Promise.all([
            buildLineageLayout(lineageGraph, compactOpts),
            buildLineageLayout(lineageGraph, fullscreenOpts),
        ]).then(([compact, fullscreen]) => {
            if (!cancelled) {
                setCompactLayout(compact)
                setFullscreenLayout(fullscreen)
            }
        })
        return () => {
            cancelled = true
        }
    }, [lineageGraph, overrides])

    // Memoize node types to avoid ReactFlow re-registering on every render
    const stableCompactNodeTypes = useMemo(() => compactNodeTypes, [])
    const stableFullscreenNodeTypes = useMemo(() => fullscreenNodeTypes, [])

    // Show spinner while fetching lineage data OR while ELK is computing the layout
    const isLayoutPending = !compactLayout && !!lineageGraph && lineageGraph.nodes.length > 1

    if (lineageGraphLoading || isLayoutPending) {
        return (
            <div className="space-y-2 mt-4">
                <h3 className="text-lg font-semibold">Lineage</h3>
                <div className="flex items-center justify-center h-72 border rounded bg-bg-light">
                    <Spinner />
                </div>
            </div>
        )
    }

    if (!compactLayout || compactLayout.nodes.length <= 1) {
        return (
            <div className="space-y-2 mt-4">
                <h3 className="text-lg font-semibold">Lineage</h3>
                <div className="text-muted text-sm">No upstream or downstream dependencies found.</div>
            </div>
        )
    }

    return (
        <div className="space-y-2 mt-4">
            <h3 className="text-lg font-semibold">Lineage</h3>
            <div className="h-72 w-full border rounded bg-bg-light">
                <ReactFlowProvider>
                    <LineageGraphContent
                        layout={compactLayout}
                        nodeTypes={stableCompactNodeTypes}
                        onFullscreen={openLineageModal}
                    />
                </ReactFlowProvider>
            </div>
            <LemonModal
                isOpen={lineageModalOpen}
                onClose={closeLineageModal}
                title="Lineage"
                width="calc(100vw - 4rem)"
                maxWidth="calc(100vw - 4rem)"
            >
                <div style={{ height: 'calc(100vh - 12rem)' }}>
                    <ReactFlowProvider>
                        <LineageGraphContent
                            layout={fullscreenLayout ?? compactLayout}
                            nodeTypes={stableFullscreenNodeTypes}
                            interactive
                        />
                    </ReactFlowProvider>
                </div>
            </LemonModal>
        </div>
    )
}
