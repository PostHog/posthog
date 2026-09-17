import { DashboardTemplateType } from '~/types'

import { DashboardTemplateClickFlowActions, runDashboardTemplateClickFlow } from './dashboardTemplateCreationFlows'

function makeTemplate(variableCount: number): DashboardTemplateType {
    return {
        id: 'tpl-1',
        template_name: 'Template',
        dashboard_description: '',
        tiles: [],
        variables: Array.from({ length: variableCount }, (_, i) => ({
            id: `VARIABLE_${i}`,
            name: `variable ${i}`,
            default: { event: '$pageview' },
            description: '',
            required: true,
            type: 'event' as const,
        })),
    }
}

function makeActions(): jest.Mocked<DashboardTemplateClickFlowActions> {
    return {
        setIsLoading: jest.fn(),
        createDashboardFromTemplate: jest.fn(),
        showVariableSelectModal: jest.fn(),
        setActiveDashboardTemplate: jest.fn(),
    }
}

describe('runDashboardTemplateClickFlow', () => {
    it('marks loading and creates straight away when the template has no variables', () => {
        const actions = makeActions()

        runDashboardTemplateClickFlow(makeTemplate(0), {
            isLoading: false,
            newDashboardModalVisible: false,
            redirectAfterCreation: true,
            ...actions,
        })

        expect(actions.setIsLoading).toHaveBeenCalledWith(true)
        expect(actions.createDashboardFromTemplate).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['opens the variable modal', false, 'showVariableSelectModal' as const],
        ['swaps the active template', true, 'setActiveDashboardTemplate' as const],
    ])('%s without marking loading', (_name, newDashboardModalVisible, expectedAction) => {
        const actions = makeActions()

        runDashboardTemplateClickFlow(makeTemplate(1), {
            isLoading: false,
            newDashboardModalVisible,
            redirectAfterCreation: true,
            ...actions,
        })

        expect(actions[expectedAction]).toHaveBeenCalledTimes(1)
        // Latching `isLoading` here left the re-entrancy guard swallowing every later template click.
        expect(actions.setIsLoading).not.toHaveBeenCalled()
        expect(actions.createDashboardFromTemplate).not.toHaveBeenCalled()
    })

    it('ignores a click while a create is already in flight', () => {
        const actions = makeActions()

        runDashboardTemplateClickFlow(makeTemplate(0), {
            isLoading: true,
            newDashboardModalVisible: true,
            redirectAfterCreation: true,
            ...actions,
        })

        expect(actions.createDashboardFromTemplate).not.toHaveBeenCalled()
        expect(actions.setIsLoading).not.toHaveBeenCalled()
    })
})
