import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'

import { duplicateDashboardLogic } from './duplicateDashboardLogic'

const SOURCE_DASHBOARD_ID = 1
const NEW_DASHBOARD_ID = 99

describe('duplicateDashboardLogic', () => {
    let logic: ReturnType<typeof duplicateDashboardLogic.build>

    function mountLogics(): void {
        dashboardsModel.mount()
        logic = duplicateDashboardLogic()
        logic.mount()
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': { count: 0, results: [] },
            },
        })
        initKeaTests()
    })

    it('keeps the modal open and shows the API error when the create fails', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/dashboards/': () => [
                    400,
                    { type: 'validation_error', detail: 'Dashboard limit reached' },
                ],
            },
        })
        mountLogics()
        logic.actions.showDuplicateDashboardModal(SOURCE_DASHBOARD_ID, 'Sales')

        await expectLogic(logic, () => {
            logic.actions.submitDuplicateDashboard()
        })
            .toDispatchActions(['submitDuplicateDashboardFailure'])
            .toMatchValues({
                duplicateError: 'Dashboard limit reached',
                duplicateDashboardModalVisible: true,
                isDuplicateDashboardSubmitting: false,
            })
    })

    it('closes the modal and clears the error on success', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/dashboards/': () => [
                    201,
                    { id: NEW_DASHBOARD_ID, name: 'Sales (Copy)', tiles: [] },
                ],
            },
        })
        mountLogics()
        logic.actions.showDuplicateDashboardModal(SOURCE_DASHBOARD_ID, 'Sales')

        await expectLogic(logic, () => {
            logic.actions.submitDuplicateDashboard()
        })
            // The button stays disabled while the create is in flight, then re-enables once it settles.
            .toMatchValues({ isDuplicateDashboardSubmitting: true })
            .toDispatchActions(['submitDuplicateDashboardSuccess'])
            .toMatchValues({
                isDuplicateDashboardSubmitting: false,
                duplicateError: null,
                duplicateDashboardModalVisible: false,
            })
    })

    it('redirects to the new dashboard exactly once when duplicating and going to it', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/dashboards/': () => [
                    201,
                    { id: NEW_DASHBOARD_ID, name: 'Sales (Copy)', tiles: [] },
                ],
            },
        })
        mountLogics()
        const pushSpy = jest.spyOn(router.actions, 'push')
        logic.actions.showDuplicateDashboardModal(SOURCE_DASHBOARD_ID, 'Sales')

        await expectLogic(logic, () => {
            logic.actions.duplicateAndGoToDashboard()
        }).toDispatchActions(['submitDuplicateDashboardSuccess'])

        const pushesToNewDashboard = pushSpy.mock.calls.filter(([url]) => url === urls.dashboard(NEW_DASHBOARD_ID))
        expect(pushesToNewDashboard).toHaveLength(1)
    })
})
