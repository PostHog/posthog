import { Edge, Node } from 'reactflow'
import { actions, afterMount, kea, path, reducers, props, key, selectors, connect } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

import { AnyAutomationStep, Automation, AutomationEdge, AutomationStepKind } from './schema'

import type { automationLogicType } from './automationLogicType'
import { teamLogic } from 'scenes/teamLogic'

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

const NEW_AUTOMATION: Automation = {
    id: 'new',
    name: '',
    created_at: null,
    created_by: null,
    updated_at: null,
    steps: [],
    edges: [],
}
export interface AutomationLogicProps {
    automationId?: Automation['id']
}

export const automationLogic = kea<automationLogicType>([
    props({} as AutomationLogicProps),
    key((props) => props.automationId || 'new'),
    path((key) => ['scenes', 'automations', 'automationLogic', key]),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        setFlowSteps: (flowSteps: Node[]) => ({ flowSteps }),
        setFlowEdges: (flowEdges: Edge[]) => ({ flowEdges }),
        setEditAutomation: (editing: boolean) => ({ editing }),
    }),
    reducers({
        editingExistingAutomation: [
            false,
            {
                setEditAutomation: (_, { editing }) => editing,
            },
        ],
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
    loaders(({ props, values }) => ({
        automation: {
            loadAutomation: async () => {
                if (props.automationId && props.automationId !== 'new') {
                    try {
                        const response = await api.get(
                            `api/projects/${values.currentTeamId}/automations/${props.automationId}`
                        )
                        return response as Automation
                    } catch (error: any) {
                        if (error.status === 404) {
                            throw error
                        } else {
                            lemonToast.error(`Failed to load automation ${props.automationId}`)
                            throw new Error(`Failed to load automation ${props.automationId}`)
                        }
                    }
                }
                return NEW_AUTOMATION
            },
            updateAutomation: async (update: Partial<Automation>) => {
                const response: Automation = await api.update(
                    `api/projects/${values.currentTeamId}/automations/${values.automationId}`,
                    update
                )
                return response
            },
        },
    })),
    selectors({
        props: [() => [(_, props) => props], (props) => props],
        automationId: [
            () => [(_, props) => props.automationId ?? 'new'],
            (automationId): Automation['id'] => automationId,
        ],
    }),
    urlToAction(({ actions, values }) => ({
        '/automations/:id': ({ id }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            actions.setEditAutomation(false)

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.resetAutomation()
                }

                if (parsedId !== 'new' && parsedId === values.automationId) {
                    actions.loadAutomation()
                }
            }
        },
    })),
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
