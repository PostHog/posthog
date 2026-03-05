import '@xyflow/react/dist/style.css'

import {
    Background,
    BackgroundVariant,
    Controls,
    MarkerType,
    NodeTypes,
    ReactFlow,
    ReactFlowProvider,
} from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useMemo, useState } from 'react'

import { IconExpand } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import type { DataModelingJobStatus } from '~/types'

import { NodeCompact, NodeInner } from '../data-warehouse/scene/modeling/Node'
import { Edge, Node, NodeData } from '../data-warehouse/scene/modeling/types'
import { nodeDetailSceneLogic, NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'

function useNodeClick(
    nodeId: string,
    data: NodeData,
    currentNode?: { id: string; name: string } | undefined
): () => void {
    return useCallback((): void => {
        if (data.type === 'endpoint') {
            const versionMatch = data.name.match(/^(.+)_v(\d+)$/)
            const endpointUrl = versionMatch
                ? urls.endpoint(versionMatch[1], parseInt(versionMatch[2]))
                : urls.endpoint(data.name)
            const searchParams = currentNode
                ? { from_node: currentNode.id, from_node_name: currentNode.name }
                : undefined
            router.actions.push(endpointUrl, searchParams)
        } else {
            const nodeSearchParams = currentNode
                ? { from_node: currentNode.id, from_node_name: currentNode.name }
                : undefined
            router.actions.push(urls.nodeDetail(nodeId), nodeSearchParams)
        }
    }, [nodeId, data.type, data.name, currentNode?.id, currentNode?.name])
}

function currentNodeFromData(data: NodeData): { id: string; name: string } | undefined {
    return data.currentNodeId
        ? { id: data.currentNodeId as string, name: (data.currentNodeName as string) ?? '' }
        : undefined
}

function CompactLineageNode(props: { id: string; data: NodeData }): JSX.Element {
    const handleNodeClick = useNodeClick(props.id, props.data, currentNodeFromData(props.data))

    return (
        <NodeCompact
            name={props.data.name}
            type={props.data.type}
            handles={props.data.handles}
            lastJobStatus={props.data.lastJobStatus}
            isSearchMatch={props.data.isSearchMatch}
            onNodeClick={handleNodeClick}
        />
    )
}

function FullLineageNode(props: { id: string; data: NodeData }): JSX.Element {
    const handleNodeClick = useNodeClick(props.id, props.data, currentNodeFromData(props.data))
    const noop = useCallback((e: React.MouseEvent) => e.stopPropagation(), [])
    const noopVoid = useCallback(() => {}, [])

    return (
        <NodeInner
            {...props.data}
            layoutDirection="RIGHT"
            onRunUpstream={noop}
            onRunDownstream={noop}
            onMaterialize={noop}
            onNodeClick={handleNodeClick}
            onMouseEnter={noopVoid}
            onMouseLeave={noopVoid}
        />
    )
}

const COMPACT_NODE_TYPES: NodeTypes = {
    model: CompactLineageNode,
}

const FULL_NODE_TYPES: NodeTypes = {
    model: FullLineageNode,
}

const FIT_VIEW_OPTIONS = { padding: 0.3, maxZoom: 1 }

function LineageGraphContent({
    id,
    className,
    fullscreen = false,
}: NodeDetailSceneLogicProps & { className?: string; fullscreen?: boolean }): JSX.Element {
    const logicProps = { id }
    const { lineageGraph, lineageGraphLoading, node, latestJobStatus, latestJobMetadataByNodeId } = useValues(
        nodeDetailSceneLogic(logicProps)
    )
    const { isDarkModeOn } = useValues(themeLogic)
    const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)

    const graph = fullscreen ? lineageGraph?.full : lineageGraph?.compact
    const nodeTypes = fullscreen ? FULL_NODE_TYPES : COMPACT_NODE_TYPES

    const onNodeMouseEnter = useCallback((_: React.MouseEvent, rfNode: Node) => {
        setHoveredNodeId(rfNode.id)
    }, [])
    const onNodeMouseLeave = useCallback(() => {
        setHoveredNodeId(null)
    }, [])

    // Highlight edges connected to the hovered node
    const highlightedEdges = useMemo(() => {
        if (!graph?.edges || !hoveredNodeId) {
            return graph?.edges ?? []
        }
        return graph.edges.map((edge) => {
            const isConnected = edge.source === hoveredNodeId || edge.target === hoveredNodeId
            if (!isConnected) {
                return edge
            }
            return {
                ...edge,
                style: { stroke: 'var(--primary-3000)' },
                markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--primary-3000)' },
            }
        })
    }, [graph?.edges, hoveredNodeId])

    if (lineageGraphLoading || !graph) {
        return (
            <div className={`flex items-center justify-center ${className ?? 'h-72'}`}>
                <Spinner className="text-2xl" />
            </div>
        )
    }

    if (graph.nodes.length <= 1) {
        return (
            <div className={`flex items-center justify-center text-muted ${className ?? 'h-72'}`}>
                No upstream or downstream nodes
            </div>
        )
    }

    // Enrich all nodes with live job metadata, and highlight the current node
    const highlightedNodes = graph.nodes.map((n) => {
        const isCurrentNode = n.id === node?.id
        const metadata = latestJobMetadataByNodeId[n.id]
        const lastJobStatus = isCurrentNode
            ? ((latestJobStatus as DataModelingJobStatus) ?? metadata?.status ?? n.data.lastJobStatus)
            : (metadata?.status ?? n.data.lastJobStatus)
        const lastRunAt = metadata?.lastRunAt ?? n.data.lastRunAt
        return {
            ...n,
            data: {
                ...n.data,
                isSearchMatch: isCurrentNode ? true : undefined,
                lastJobStatus,
                lastRunAt,
                currentNodeId: node?.id,
                currentNodeName: node?.name,
            },
        }
    })

    return (
        <div className={className ?? 'h-72'}>
            <ReactFlow<Node, Edge>
                fitView
                nodes={highlightedNodes}
                edges={highlightedEdges}
                nodeTypes={nodeTypes}
                nodesDraggable={false}
                nodesConnectable={false}
                onNodeMouseEnter={onNodeMouseEnter}
                onNodeMouseLeave={onNodeMouseLeave}
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                fitViewOptions={FIT_VIEW_OPTIONS}
                proOptions={{ hideAttribution: true }}
                elevateNodesOnSelect={false}
                minZoom={0.25}
                maxZoom={1.5}
                zoomOnScroll={false}
                panOnScroll={false}
                preventScrolling={false}
                zoomOnPinch
                panOnDrag
                zoomOnDoubleClick
            >
                <Background gap={36} variant={BackgroundVariant.Dots} bgColor="var(--color-bg-primary)" />
                {fullscreen && <Controls showInteractive={false} fitViewOptions={FIT_VIEW_OPTIONS} />}
            </ReactFlow>
        </div>
    )
}

export function NodeDetailLineage({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const logicProps = { id }
    const { openLineageModal } = useActions(nodeDetailSceneLogic(logicProps))

    return (
        <div className="space-y-2">
            <LemonLabel className="text-base font-semibold" info="Upstream and downstream dependencies of this model">
                Lineage
            </LemonLabel>
            <div className="relative border rounded-lg overflow-hidden">
                <ReactFlowProvider>
                    <LineageGraphContent id={id} className="h-72" />
                </ReactFlowProvider>
                <div className="absolute top-2 right-2 z-10">
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconExpand />}
                        onClick={openLineageModal}
                        tooltip="Fullscreen"
                    />
                </div>
            </div>
        </div>
    )
}

export function NodeDetailLineageFullscreen({ id }: NodeDetailSceneLogicProps): JSX.Element {
    return (
        <ReactFlowProvider>
            <LineageGraphContent id={id} className="h-full w-full" fullscreen />
        </ReactFlowProvider>
    )
}
