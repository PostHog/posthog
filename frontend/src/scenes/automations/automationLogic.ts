import { actions, afterMount, kea, path, reducers } from 'kea'
import { Edge, Node } from 'reactflow'

import { AnyAutomationStep, AutomationEdge, AutomationStepKind } from './schema'

import type { automationLogicType } from './automationLogicType'

const savedSteps: AnyAutomationStep[] = [
    // {
    //     id: '1',
    //     kind: AutomationStepKind.EventSource,
    // },
    // {
    //     id: '2',
    //     kind: AutomationStepKind.WebhookDestination,
    //     url: 'https://example-webhook-destination.com',
    // },
]

const savedEdges: Edge[] = [
    {
        id: '1=>2',
        source: '1',
        target: '2',
    },
]

export const automationLogic = kea<automationLogicType>([
    path(['scenes', 'automations', 'automationsLogic']),
    actions({
        setFlowSteps: (flowSteps: Node[]) => ({ flowSteps }),
        setFlowEdges: (flowEdges: Edge[]) => ({ flowEdges }),
    }),
    reducers({
        flowSteps: [
            [] as Node[],
            {
                setFlowSteps: (_, { flowSteps }) => flowSteps,
            },
        ],
        flowEdges: [
            [] as Edge[],
            {
                setFlowEdges: (_, { flowEdges }) => flowEdges,
            },
        ],
    }),
    afterMount(({ actions }) => {
        const flowSteps = savedSteps.map((step: AnyAutomationStep) => {
            return {
                id: step.id,
                data: { label: step.kind },
                position: { x: 0, y: 0 },
                type: 'workflow',
            } as Node
        })

        const flowEdges = savedEdges.map((edge: AutomationEdge, index: number) => ({
            id: index.toString(),
            source: edge.source,
            target: edge.target,
            type: 'workflow',
        }))

        // TODO: add this for each node in the tree

        if (!flowSteps.length || flowSteps[flowSteps.length - 1].data.label !== AutomationStepKind.WebhookDestination) {
            flowSteps.push({
                id: 'placeholder',
                data: { label: 'placeholder' },
                position: { x: 0, y: 0 },
                type: 'placeholder',
            } as Node)
            // add a placeholder edge
            if (flowSteps.length > 1) {
                flowEdges.push({
                    id: flowEdges.length.toString(),
                    source: flowSteps[flowSteps.length - 2].id,
                    target: 'placeholder',
                    type: 'placeholder',
                })
            }
        }

        actions.setFlowSteps(flowSteps)
        actions.setFlowEdges(flowEdges)
    }),
])
