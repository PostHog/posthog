import { Edge, Node } from 'reactflow'
import {
    AnyAutomationStep,
    AutomationEdge,
    AutomationEventSourceStep,
    AutomationStepKind,
    AutomationWebhookDestinationStep,
    AutomationSlackDestinationStep,
} from './schema'
import { uuid } from 'lib/utils'

const SEPARATION = 150

export const stepsToFlowSteps = (steps: AnyAutomationStep[]): Node[] => {
    return steps.map((step: AnyAutomationStep, index) => {
        return {
            type: 'workflow',
            id: step.id,
            data: step,
            position: { x: 0, y: index * SEPARATION },
        }
    })
}

export const edgesToFlowEdges = (edges: AutomationEdge[]): Edge[] => {
    return edges.map((edge: AutomationEdge) => ({
        type: 'workflow',
        ...edge,
    }))
}

export const addPlaceholderFlowSteps = (flowSteps: Node[]): Node[] => {
    // TODO: add placeholder steps for all branches
    if (!flowSteps.length || flowSteps[flowSteps.length - 1].data.label !== AutomationStepKind.WebhookDestination) {
        return [
            ...flowSteps,
            {
                type: 'placeholder',
                id: uuid(),
                data: { label: 'placeholder' },
                position: { x: 0, y: flowSteps.length * SEPARATION },
            },
        ]
    }

    return flowSteps
}

export const addPlaceholderFlowEdges = (flowEdges: Edge[], flowSteps: Node[]): Edge[] => {
    // TODO: add placeholder steps for all branches
    if (flowSteps.length > 1) {
        return [
            ...flowEdges,
            {
                type: 'placeholder',
                id: uuid(),
                source: flowSteps[flowSteps.length - 2].id,
                target: flowSteps[flowSteps.length - 1].id,
            },
        ]
    }

    return flowEdges
}

export function isAutomationEventSourceStep(node?: AnyAutomationStep | null): node is AutomationEventSourceStep {
    return node?.kind === AutomationStepKind.EventSource
}

export function isAutomationWebhookDestinationStep(
    node?: AnyAutomationStep | null
): node is AutomationWebhookDestinationStep {
    return node?.kind === AutomationStepKind.WebhookDestination
}

export function isAutomationSlackDestinationStep(
    node?: AnyAutomationStep | null
): node is AutomationSlackDestinationStep {
    return node?.kind === AutomationStepKind.SlackDestination
}
