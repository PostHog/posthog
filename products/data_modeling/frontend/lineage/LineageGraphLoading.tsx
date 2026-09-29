import { Background, BackgroundVariant, FitViewOptions, ReactFlow, useReactFlow } from '@xyflow/react'
import { useValues } from 'kea'
import { useEffect, useId, useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DataModelingEdge, DataModelingNode } from '~/types'

import { ElkDirection } from './autolayout'
import { initialLineageGraphLayout, lineageGraphLogic } from './lineageGraphLogic'
import { LINEAGE_NODE_TYPES, LineageVariant } from './LineageNode'

export interface LineageGraphLoadingProps {
    center?: Pick<DataModelingNode, 'name' | 'type'>
    direction: ElkDirection
    fitViewOptions?: FitViewOptions
    variant: LineageVariant
}

function loadingGraph(
    idPrefix: string,
    center?: Pick<DataModelingNode, 'name' | 'type'>
): {
    nodes: DataModelingNode[]
    edges: DataModelingEdge[]
    centerNodeId?: string
} {
    const dag = 'lineage-loading'
    const node = (id: string, name: string, type: DataModelingNode['type']): DataModelingNode => ({
        id,
        name,
        type,
        dag,
        created_at: '',
        updated_at: '',
        upstream_count: 0,
        downstream_count: 0,
    })
    const edge = (id: string, source_id: string, target_id: string): DataModelingEdge => ({
        id,
        source_id,
        target_id,
        dag,
        properties: {},
        created_at: '',
        updated_at: '',
    })
    const upstreamId = `${idPrefix}-upstream`
    const centerNodeId = `${idPrefix}-center`
    const downstreamId = `${idPrefix}-downstream`

    if (!center) {
        return {
            nodes: [node(upstreamId, '', 'view'), node(downstreamId, '', 'view')],
            edges: [edge(`${idPrefix}-edge`, upstreamId, downstreamId)],
        }
    }

    return {
        centerNodeId,
        nodes: [
            node(upstreamId, 'Loading upstream...', 'table'),
            node(centerNodeId, center.name, center.type),
            node(downstreamId, 'Loading downstream...', 'view'),
        ],
        edges: [
            edge(`${idPrefix}-upstream-edge`, upstreamId, centerNodeId),
            edge(`${idPrefix}-downstream-edge`, centerNodeId, downstreamId),
        ],
    }
}

export function LineageGraphLoading({
    center,
    direction,
    fitViewOptions,
    variant,
}: LineageGraphLoadingProps): JSX.Element {
    const { fitView, viewportInitialized } = useReactFlow()
    const { isDarkModeOn } = useValues(themeLogic)
    const reactId = useId()
    const idPrefix = useMemo(() => `lineage-loading-${reactId.replaceAll(':', '')}`, [reactId])
    const graph = useMemo(() => loadingGraph(idPrefix, center), [center?.name, center?.type, idPrefix])
    const { layout } = useValues(
        lineageGraphLogic({
            nodes: graph.nodes,
            edges: graph.edges,
            variant,
            direction,
        })
    )
    const displayedLayout = layout ?? initialLineageGraphLayout(graph.nodes, graph.edges, variant, direction)
    const loadingFitViewOptions = useMemo(
        () => ({
            ...fitViewOptions,
            maxZoom: Math.min(fitViewOptions?.maxZoom ?? 1, 1),
        }),
        [fitViewOptions]
    )

    useEffect(() => {
        if (viewportInitialized) {
            void fitView({
                ...loadingFitViewOptions,
                nodes: displayedLayout.nodes,
                padding: loadingFitViewOptions.padding ?? 0.2,
                duration: 0,
            })
        }
    }, [displayedLayout, fitView, loadingFitViewOptions, viewportInitialized])

    const nodes = displayedLayout.nodes.map((node) => ({
        ...node,
        data: {
            ...node.data,
            state: {
                loading: node.id === graph.centerNodeId && center ? ('focus' as const) : ('placeholder' as const),
            },
            callbacks: {},
        },
    }))
    const edges = displayedLayout.edges.map((edge) => ({
        ...edge,
        className: 'opacity-50',
    }))

    return (
        <>
            <span className="sr-only" role="status">
                Loading lineage
            </span>
            <ReactFlow
                aria-hidden="true"
                colorMode={isDarkModeOn ? 'dark' : 'light'}
                nodes={nodes}
                edges={edges}
                nodeTypes={LINEAGE_NODE_TYPES}
                nodesDraggable={false}
                nodesConnectable={false}
                nodesFocusable={false}
                elementsSelectable={false}
                fitView
                fitViewOptions={loadingFitViewOptions}
                minZoom={0.1}
                maxZoom={1}
                zoomOnScroll={false}
                panOnScroll={false}
                panOnDrag={false}
                zoomOnPinch={false}
                zoomOnDoubleClick={false}
                proOptions={{ hideAttribution: true }}
            >
                <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
            </ReactFlow>
        </>
    )
}
