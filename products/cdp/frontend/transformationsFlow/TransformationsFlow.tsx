import '@xyflow/react/dist/style.css'

import { Background, BackgroundVariant, Controls, NodeTypes, ReactFlow } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { themeLogic } from 'lib/logic/themeLogic'

import { transformationsFlowLogic } from './transformationsFlowLogic'
import { TransformationsFlowNode } from './TransformationsFlowNode'
import { TransformationsFlowPanel } from './TransformationsFlowPanel'

const NODE_TYPES: NodeTypes = { flowStep: TransformationsFlowNode }

export function TransformationsFlow(): JSX.Element {
    const { graph, transformations, transformationsLoading } = useValues(transformationsFlowLogic)
    const { selectStep, loadTransformations } = useActions(transformationsFlowLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    if (transformations === null) {
        return transformationsLoading ? (
            <div className="flex justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        ) : (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadTransformations }}>
                Could not load your transformations.
            </LemonBanner>
        )
    }

    return (
        <div className="@container/transformations-flow">
            <div className="flex gap-2 items-start @max-[56rem]/transformations-flow:flex-col">
                <div
                    className="h-160 min-w-0 flex-1 border rounded overflow-hidden @max-[56rem]/transformations-flow:w-full @max-[56rem]/transformations-flow:flex-none @max-[56rem]/transformations-flow:h-120"
                    data-attr="transformations-flow-canvas"
                >
                    <ReactFlow
                        nodes={graph.nodes}
                        edges={graph.edges}
                        nodeTypes={NODE_TYPES}
                        onNodeClick={(_, node) => selectStep(node.id)}
                        onPaneClick={() => selectStep(null)}
                        nodesDraggable={false}
                        nodesConnectable={false}
                        elementsSelectable={false}
                        colorMode={isDarkModeOn ? 'dark' : 'light'}
                        fitView
                        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
                        minZoom={0.25}
                        maxZoom={1.5}
                        proOptions={{ hideAttribution: true }}
                    >
                        <Background gap={36} variant={BackgroundVariant.Dots} />
                        <Controls showInteractive={false} />
                    </ReactFlow>
                </div>
                <div className="w-120 shrink-0 @max-[56rem]/transformations-flow:w-full">
                    <TransformationsFlowPanel />
                </div>
            </div>
        </div>
    )
}
