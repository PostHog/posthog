import { Edge, Node } from 'reactflow'
import { actions, kea, path, reducers, props, key, selectors, connect, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

import { Automation } from './schema'

import type { automationLogicType } from './automationLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { addPlaceholderFlowEdges, addPlaceholderFlowSteps, edgesToFlowEdges, stepsToFlowSteps } from './utils'

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
        addStep: (step: Node) => ({ step }),
        setEditAutomation: (editing: boolean) => ({ editing }),
    }),
    reducers({
        editingExistingAutomation: [
            false,
            {
                setEditAutomation: (_, { editing }) => editing,
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
        steps: [
            (s) => [s.automation],
            (automation): Automation['steps'] => {
                if (!automation || !automation.steps || automation.steps.length === 0) {
                    return []
                }

                return automation.steps
            },
        ],
        edges: [
            (s) => [s.automation],
            (automation): Automation['edges'] => {
                if (!automation || !automation.edges || automation.edges.length === 0) {
                    return []
                }

                return automation.edges
            },
        ],
        flowSteps: [
            (s) => [s.steps],
            (steps): Node[] => {
                return addPlaceholderFlowSteps(stepsToFlowSteps(steps))
            },
        ],
        flowEdges: [
            (s) => [s.edges, s.flowSteps],
            (edges, flowSteps): Edge[] => {
                return addPlaceholderFlowEdges(edgesToFlowEdges(edges), flowSteps)
            },
        ],
    }),
    forms(({ actions, values }) => ({
        automation: {
            defaults: { ...NEW_AUTOMATION } as Automation,
            errors: ({ name }) => ({
                name: !name && 'You have to enter a name.',
            }),
            submit: () => {
                console.debug('submit')
                // actions.createExperiment(true, exposure, sampleSize)
            },
        },
    })),
    listeners(({ actions, values }) => ({
        addStep: ({ step }) => {
            console.debug('listeners.addStep: ', step)
            console.debug('values.steps: ', values.steps)

            actions.setAutomationValues({
                steps: [...values.steps, step],
                edges: [{ source: 'Event sent', target: 'placeholder', type: 'workflow' }],
            })
        },
    })),
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
])
