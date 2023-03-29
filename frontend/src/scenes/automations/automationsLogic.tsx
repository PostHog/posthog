import { actions, afterMount, kea, path, reducers } from 'kea'
import { Edge, Node } from 'reactflow'

import type { automationsLogicType } from './automationsLogicType'
import { AnyAutomationStep, AutomationEdge, AutomationStepKind } from './schema'

const savedSteps: AnyAutomationStep[] = [
    {
        id: '1',
        kind: AutomationStepKind.EventSource,
    },
    {
        id: '2',
        kind: AutomationStepKind.WebhookDestination,
        url: 'https://example-webhook-destination.com',
    },
]

const savedEdges: Edge[] = [
    {
        id: '1=>2',
        source: '1',
        target: '2',
    },
]

export const automationsLogic = kea<automationsLogicType>([
    path(['scenes', 'automations', 'automationsLogic']),
    actions({
        setFlowSteps: (flowSteps: Node[]) => ({ flowSteps }),
        setFlowEdges: (flowEdges: Edge[]) => ({ flowEdges }),
        fromAutomationSteps: (steps: AnyAutomationStep[]) => ({ steps }),
        fromAutomationEdges: (edges: AutomationEdge[]) => ({ edges }),
    }),
    reducers({
        flowSteps: [
            [] as Node[],
            {
                setFlowSteps: (state, { flowSteps }) => flowSteps,
                fromAutomationSteps: (state, { steps }) => {
                    return steps.map((step: AnyAutomationStep) => {
                        return {
                            id: step.id,
                            data: { label: step.kind },
                            position: { x: 0, y: 0 },
                            type: 'workflow',
                        } as Node
                    })
                },
            },
        ],
        flowEdges: [
            [] as Edge[],
            {
                setFlowEdges: (_, { flowEdges }) => flowEdges,
                fromAutomationEdges: (_, { edges }) => {
                    return edges.map((edge: AutomationEdge, index: number) => ({
                        id: index.toString(),
                        source: edge.source,
                        target: edge.target,
                        type: 'workflow',
                    }))
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.fromAutomationSteps(savedSteps)
        actions.fromAutomationEdges(savedEdges)
    }),
])
