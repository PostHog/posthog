import '@xyflow/react/dist/style.css'

import { Node, NodeTypes, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightQueryNode } from '~/queries/schema/schema-general'
import { FunnelStepWithConversionMetrics, InsightLogicProps } from '~/types'

import funnelInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'

let uniqueNode = 0

export function InsightProvider({ children }: { children: React.ReactNode }): JSX.Element {
    const [dashboardItemId] = useState(() => `NodeStory.${uniqueNode++}`)

    const cachedInsight = { ...funnelInsight, short_id: dashboardItemId }
    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as unknown as InsightLogicProps
    const source = funnelInsight.query.source as unknown as InsightQueryNode

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(insightProps.cachedInsight, source),
        doNotLoad: insightProps.doNotLoad,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                {children}
            </BindLogic>
        </BindLogic>
    )
}

export function makeStep(name: string, order: number, count: number, total: number): FunnelStepWithConversionMetrics {
    const fromPrevious = order === 0 ? 1 : total > 0 ? count / total : 0
    return {
        action_id: name,
        name,
        custom_name: null,
        order,
        count,
        type: 'events',
        average_conversion_time: order > 0 ? 120 : null,
        median_conversion_time: order > 0 ? 90 : null,
        converted_people_url: '/api/person/funnel/?',
        dropped_people_url: order > 0 ? '/api/person/funnel/?' : null,
        droppedOffFromPrevious: total - count,
        conversionRates: { fromPrevious, total: fromPrevious, fromBasisStep: fromPrevious },
    } as unknown as FunnelStepWithConversionMetrics
}

export function pathNode(id: string, type: string, data: Record<string, unknown>, x: number): Node {
    return {
        id,
        type,
        data,
        position: { x, y: 0 },
        draggable: false,
        connectable: false,
    }
}

export function NodeCanvas<T extends Record<string, unknown>>({
    nodes,
    nodeTypes,
    height = 200,
    width = 800,
    padding = 0.3,
}: {
    nodes: Node<T>[]
    nodeTypes: NodeTypes
    height?: number
    width?: number
    padding?: number
}): JSX.Element {
    return (
        <ReactFlowProvider>
            <div style={{ width, height }}>
                <ReactFlow
                    nodes={nodes}
                    edges={[]}
                    nodeTypes={nodeTypes}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    fitView
                    fitViewOptions={{ padding }}
                    proOptions={{ hideAttribution: true }}
                    minZoom={0.5}
                    maxZoom={1}
                />
            </div>
        </ReactFlowProvider>
    )
}
