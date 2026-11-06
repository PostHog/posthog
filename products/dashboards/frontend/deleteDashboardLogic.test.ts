import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { deleteDashboardLogic } from './deleteDashboardLogic'

describe('deleteDashboardLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': { count: 0, results: [] },
            },
            patch: {
                '/api/environments/:team_id/dashboards/:id/': { id: 7, name: 'To delete', deleted: true },
            },
        })
        initKeaTests()
    })

    it('sends the user from the deleted dashboard to the dashboards list', async () => {
        router.actions.push(urls.dashboard(7))
        const logic = deleteDashboardLogic()
        logic.mount()

        logic.actions.showDeleteDashboardModal(7)
        logic.actions.submitDeleteDashboard()

        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.dashboards()}$`))
        expect(logic.values.deleteDashboardModalVisible).toBe(false)
    })
})
