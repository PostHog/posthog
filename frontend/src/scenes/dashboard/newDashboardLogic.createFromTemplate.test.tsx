import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import type { DashboardTemplateType } from '~/types'

import { newDashboardLogic } from './newDashboardLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const template = {
    id: 'tpl-1',
    template_name: 'Website traffic',
    dashboard_description: '',
    tiles: [{ type: 'TEXT', body: 'hello', layouts: {} }],
    variables: [],
} as unknown as DashboardTemplateType

describe('newDashboardLogic creating a dashboard from a template', () => {
    let logic: ReturnType<typeof newDashboardLogic.build>
    let settleCreate: { resolve: (dashboard: unknown) => void; reject: (error: unknown) => void }

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(router.actions, 'push')
        jest.spyOn(api, 'create').mockImplementation(
            () =>
                new Promise((resolve, reject) => {
                    settleCreate = { resolve, reject }
                })
        )
        logic = newDashboardLogic({})
        logic.mount()
        logic.actions.showVariableSelectModal(template)
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('keeps the modal open and loading while the request is in flight', async () => {
        logic.actions.createDashboardFromTemplate(template, [])

        await expectLogic(logic).toMatchValues({
            isLoading: true,
            newDashboardModalVisible: true,
            activeDashboardTemplate: template,
        })
        expect(router.actions.push).not.toHaveBeenCalled()
    })

    it('leaves the template selected so Create can be retried after a failure', async () => {
        logic.actions.createDashboardFromTemplate(template, [])

        settleCreate.reject(new ApiError('nope', 500))
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(router.actions.push).not.toHaveBeenCalled()
        expectLogic(logic).toMatchValues({
            isLoading: false,
            newDashboardModalVisible: true,
            activeDashboardTemplate: template,
        })
    })

    it('closes the modal and redirects once the dashboard exists', async () => {
        logic.actions.createDashboardFromTemplate(template, [])

        settleCreate.resolve({ id: 42, name: 'Website traffic', tiles: [] })
        await expectLogic(logic).toFinishAllListeners()

        expect(router.actions.push).toHaveBeenCalledWith(urls.dashboard(42))
        expectLogic(logic).toMatchValues({
            isLoading: false,
            newDashboardModalVisible: false,
            activeDashboardTemplate: null,
        })
    })
})
