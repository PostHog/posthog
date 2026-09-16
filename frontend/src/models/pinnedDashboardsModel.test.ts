import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { pinnedDashboardsModel } from './pinnedDashboardsModel'

describe('pinnedDashboardsModel', () => {
    it('reloads pinned dashboards after switching projects', async () => {
        let dashboardId = 1
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': () => [
                    200,
                    { results: [{ id: dashboardId, name: `Dashboard ${dashboardId}` }] },
                ],
            },
        })
        initKeaTests()

        const logic = pinnedDashboardsModel()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPinnedDashboardsSuccess'])
        expect(logic.values.pinnedDashboards).toMatchObject([{ id: 1 }])

        dashboardId = 2
        await expectLogic(logic, () => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 2 })
        }).toDispatchActions(['loadPinnedDashboardsSuccess'])

        expect(logic.values.pinnedDashboards).toMatchObject([{ id: 2 }])
    })
})
