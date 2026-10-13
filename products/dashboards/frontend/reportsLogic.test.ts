import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { reportsLogic } from './reportsLogic'

describe('creating a report in a folder', () => {
    it('creates one dashboard in the current folder without changing Home', async () => {
        const requests: Record<string, unknown>[] = []
        useMocks({
            post: {
                '/api/environments/:team/dashboards/': async ({ request }) => {
                    requests.push((await request.json()) as Record<string, unknown>)
                    return [201, { id: 123, name: 'New dashboard' }]
                },
            },
        })
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, home_tab_dashboard: 42 })
        const dashboardLogic = newDashboardLogic()
        dashboardLogic.mount()
        dashboardLogic.actions.setAsHomeTabDashboardAfterCreation(true)
        const logic = reportsLogic({ folder: 'Sales/Quarter 1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
            logic.actions.createDashboard()
        }).toFinishAllListeners()

        expect(requests).toEqual([
            expect.objectContaining({ _create_in_folder: 'Sales/Quarter 1', name: 'New dashboard' }),
        ])
        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBe(42)
    })
})
