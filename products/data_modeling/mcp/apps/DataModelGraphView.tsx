import {
    Background,
    Controls,
    type Edge as ReactFlowEdge,
    MarkerType,
    type Node as ReactFlowNode,
    Panel,
    Position,
    ReactFlow,
} from '@xyflow/react'
import { type MouseEvent as ReactMouseEvent, type ReactElement, useEffect, useMemo, useState } from 'react'

import { layoutGraph, type NodePosition } from './autolayout'
import { computeLineage } from './highlight'
import { type LineageNodeData, REACT_FLOW_NODE_TYPES } from './LineageNode'
import type { DataModelEdge, DataModelGraphData, NodeRole } from './types'

const UPSTREAM_COLOR = 'rgb(59 130 246)' // blue-500
const DOWNSTREAM_COLOR = 'rgb(249 115 22)' // orange-500
const MUTED_COLOR = 'rgb(148 163 184)' // slate-400

function edgeColor(
    edge: DataModelEdge,
    focalId: string | null,
    upstreamIds: Set<string>,
    downstreamIds: Set<string>
): string {
    if (!focalId) {
        return MUTED_COLOR
    }
    const inUpstream = (id: string): boolean => id === focalId || upstreamIds.has(id)
    const inDownstream = (id: string): boolean => id === focalId || downstreamIds.has(id)
    if (inUpstream(edge.source_id) && inUpstream(edge.target_id)) {
        return UPSTREAM_COLOR
    }
    if (inDownstream(edge.source_id) && inDownstream(edge.target_id)) {
        return DOWNSTREAM_COLOR
    }
    return MUTED_COLOR
}

function LegendDot({ color, label }: { color: string; label: string }): ReactElement {
    return (
        <span className="flex items-center gap-1">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            {label}
        </span>
    )
}

export function DataModelGraphView({ data }: { data: DataModelGraphData }): ReactElement {
    const [focalId, setFocalId] = useState<string | null>(data.focal_id)
    const [positions, setPositions] = useState<Record<string, NodePosition> | null>(null)

    useEffect(() => {
        let cancelled = false
        layoutGraph(data.nodes, data.edges)
            .then((result) => {
                if (!cancelled) {
                    setPositions(result)
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setPositions({})
                }
            })
        return () => {
            cancelled = true
        }
    }, [data.nodes, data.edges])

    const lineage = useMemo(() => computeLineage(data.edges, focalId), [data.edges, focalId])

    const rfNodes = useMemo<ReactFlowNode<LineageNodeData>[]>(() => {
        if (!positions) {
            return []
        }
        return data.nodes.map((node) => {
            const role: NodeRole = lineage.roleOf(node.id)
            return {
                id: node.id,
                type: 'model',
                position: positions[node.id] ?? { x: 0, y: 0 },
                sourcePosition: Position.Right,
                targetPosition: Position.Left,
                data: { node, role, dimmed: focalId != null && role === 'other' },
            }
        })
    }, [data.nodes, positions, lineage, focalId])

    const rfEdges = useMemo<ReactFlowEdge[]>(() => {
        return data.edges.map((edge) => {
            const color = edgeColor(edge, focalId, lineage.upstreamIds, lineage.downstreamIds)
            return {
                id: edge.id,
                source: edge.source_id,
                target: edge.target_id,
                style: { stroke: color, strokeWidth: color === MUTED_COLOR ? 1 : 1.5 },
                markerEnd: { type: MarkerType.ArrowClosed, color },
            }
        })
    }, [data.edges, focalId, lineage])

    if (data.nodes.length === 0) {
        return (
            <div className="flex h-[400px] items-center justify-center text-sm text-muted-foreground">
                No data models found.
            </div>
        )
    }

    if (!positions) {
        return (
            <div className="flex h-[400px] items-center justify-center text-sm text-muted-foreground">
                Laying out graph…
            </div>
        )
    }

    return (
        <div className="h-[600px] w-full">
            <ReactFlow
                nodes={rfNodes}
                edges={rfEdges}
                nodeTypes={REACT_FLOW_NODE_TYPES}
                onNodeClick={(_event: ReactMouseEvent, node: ReactFlowNode<LineageNodeData>) => setFocalId(node.id)}
                fitView
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
                proOptions={{ hideAttribution: true }}
                minZoom={0.1}
            >
                <Background />
                <Controls showInteractive={false} />
                <Panel
                    position="top-left"
                    className="flex flex-col gap-1 rounded-md border border-border bg-background/90 px-2 py-1.5 text-[11px] text-muted-foreground"
                >
                    <span className="font-medium text-foreground">Upstream → focal → Downstream</span>
                    <div className="flex items-center gap-3">
                        <LegendDot color={UPSTREAM_COLOR} label="Dependencies" />
                        <LegendDot color={DOWNSTREAM_COLOR} label="Impact" />
                    </div>
                    <span>Click a node to refocus.</span>
                    {focalId != null && (
                        <button
                            type="button"
                            onClick={() => setFocalId(null)}
                            className="self-start text-link underline"
                        >
                            Clear focus
                        </button>
                    )}
                </Panel>
            </ReactFlow>
        </div>
    )
}
