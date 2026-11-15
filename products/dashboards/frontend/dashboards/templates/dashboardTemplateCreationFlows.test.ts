import { initKeaTests } from '~/test/init'
import type { DashboardTemplateType } from '~/types'

import { dashboardTemplateChooserLogic } from './dashboardTemplateChooserLogic'
import { runBlankDashboardFlow, runDashboardTemplateClickFlow } from './dashboardTemplateCreationFlows'

describe('dashboard template creation flows', () => {
    it('passes the Home navigation choice when creating a template without variables', () => {
        const template = { id: 7, template_name: 'Starter', variables: [] } as unknown as DashboardTemplateType
        const createDashboardFromTemplate = jest.fn()

        runDashboardTemplateClickFlow(template, {
            isLoading: false,
            newDashboardModalVisible: false,
            redirectAfterCreation: false,
            setIsLoading: jest.fn(),
            createDashboardFromTemplate,
            showVariableSelectModal: jest.fn(),
            setActiveDashboardTemplate: jest.fn(),
        })

        expect(createDashboardFromTemplate).toHaveBeenCalledWith(template, [], false)
    })

    it('creates a blank Home dashboard without navigating away', () => {
        const addDashboard = jest.fn()

        runBlankDashboardFlow({
            isLoading: false,
            redirectAfterCreation: false,
            setIsLoading: jest.fn(),
            addDashboard,
        })

        expect(addDashboard).toHaveBeenCalledWith(expect.objectContaining({ show: false }))
    })

    it('keeps Home and ordinary dashboard creation in separate chooser instances', () => {
        initKeaTests()

        const homeChooser = dashboardTemplateChooserLogic({ scope: 'default', redirectAfterCreation: false })
        const ordinaryChooser = dashboardTemplateChooserLogic({ scope: 'default' })

        expect(ordinaryChooser).not.toBe(homeChooser)
        expect(ordinaryChooser).toBe(dashboardTemplateChooserLogic({ scope: 'default', redirectAfterCreation: true }))
        expect(homeChooser.props.redirectAfterCreation).toBe(false)
        expect(ordinaryChooser.props.redirectAfterCreation).toBe(true)

        const addDashboard = jest.fn()
        runBlankDashboardFlow({
            isLoading: false,
            redirectAfterCreation: ordinaryChooser.props.redirectAfterCreation,
            setIsLoading: jest.fn(),
            addDashboard,
        })
        expect(addDashboard).toHaveBeenCalledWith(expect.objectContaining({ show: true }))

        const template = { id: 8, template_name: 'Starter', variables: [] } as unknown as DashboardTemplateType
        const createDashboardFromTemplate = jest.fn()
        runDashboardTemplateClickFlow(template, {
            isLoading: false,
            newDashboardModalVisible: false,
            redirectAfterCreation: ordinaryChooser.props.redirectAfterCreation ?? true,
            setIsLoading: jest.fn(),
            createDashboardFromTemplate,
            showVariableSelectModal: jest.fn(),
            setActiveDashboardTemplate: jest.fn(),
        })
        expect(createDashboardFromTemplate).toHaveBeenCalledWith(template, [], true)
    })
})
