import '@xyflow/react/dist/style.css'

import { Background, Controls, ReactFlow, useEdgesState, useNodesState } from '@xyflow/react'
import { useEffect } from 'react'

import { Survey } from '~/types'

import { NewSurvey } from '../constants'
import { EndNode } from './nodes/EndNode'
import { SurveyQuestionNode } from './nodes/SurveyQuestionNode'
import type { SurveyFlowEdge, SurveyFlowNode } from './types'
import { getLayoutedNodes } from './utils/autolayout'
import { surveyToGraph } from './utils/surveyToGraph'

interface SurveyBranchingFlowProps {
    survey: Survey | NewSurvey
}

export const nodeTypes = {
    surveyQuestion: SurveyQuestionNode,
    end: EndNode,
}

export function SurveyBranchingFlow({ survey }: SurveyBranchingFlowProps): JSX.Element {
    const [nodes, setNodes, onNodesChange] = useNodesState<SurveyFlowNode>([])
    const [edges, setEdges, onEdgesChange] = useEdgesState<SurveyFlowEdge>([])

    useEffect(() => {
        const { nodes: graphNodes, edges: graphEdges } = surveyToGraph(survey)

        void getLayoutedNodes(graphNodes, graphEdges)
            .then((layoutedNodes) => {
                setNodes(layoutedNodes)
                setEdges(graphEdges)
            })
            .catch((error) => {
                console.error('Failed to layout survey flow:', error)
                setNodes(graphNodes)
                setEdges(graphEdges)
            })
    }, [survey, setNodes, setEdges])

    return (
        <div className="w-full h-full">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                nodeTypes={nodeTypes}
                defaultEdgeOptions={{
                    style: { strokeWidth: 3, stroke: '#d0d0d0' },
                    labelStyle: { fontSize: 18, fontWeight: 600, fill: '#333' },
                    labelBgStyle: { fill: '#fff', stroke: '#d0d0d0', strokeWidth: 1 },
                    labelBgPadding: [14, 8] as [number, number],
                    labelBgBorderRadius: 8,
                }}
                fitView
                fitViewOptions={{ padding: 0.2 }}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
                panOnScroll
                zoomOnScroll
                minZoom={0.1}
                maxZoom={1.5}
            >
                <Background />
                <Controls showInteractive={false} />
            </ReactFlow>
        </div>
    )
}
