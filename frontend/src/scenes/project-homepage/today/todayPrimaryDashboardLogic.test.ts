import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todayLogic } from './todayLogic'
import { todayPrimaryDashboardLogic } from './todayPrimaryDashboardLogic'

describe('todayPrimaryDashboardLogic', () => {
    let dashboardStatus: number

    beforeEach(() => {
        // useSampleData persists to localStorage, so sample mode from one case would leak into the next
        localStorage.clear()
        dashboardStatus = 200
        useMocks({
            get: {
                '/api/projects/:team_id/dashboards/:id/': ({ params }) =>
                    dashboardStatus === 200
                        ? [200, { id: Number(params.id), name: 'Growth', description: 'Weekly **signups**' }]
                        : [dashboardStatus, { detail: 'Not found.' }],
            },
        })
        initKeaTests()
    })

    it.each([
        { name: 'shows the project dashboard', useSampleData: false, expected: 7 },
        { name: 'hides the project dashboard in sample mode', useSampleData: true, expected: null },
    ])('$name', ({ useSampleData, expected }) => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, primary_dashboard: 7 })
        const logic = todayPrimaryDashboardLogic()
        logic.mount()
        todayLogic.actions.setUseSampleData(useSampleData)

        expect(logic.values.primaryDashboardId).toBe(expected)
    })

    it.each([
        { name: 'loads the name and description for the row', status: 200, expected: 'Growth' },
        { name: 'leaves the row out when the dashboard is gone', status: 404, expected: null },
    ])('$name', async ({ status, expected }) => {
        dashboardStatus = status
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, primary_dashboard: 7 })
        const logic = todayPrimaryDashboardLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPrimaryDashboardResponseSuccess'])
        expect(logic.values.primaryDashboard?.name ?? null).toBe(expected)
    })

    it('does not show the previous dashboard after the primary dashboard changes', async () => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, primary_dashboard: 7 })
        const logic = todayPrimaryDashboardLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPrimaryDashboardResponseSuccess'])

        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, primary_dashboard: 8 })

        expect(logic.values.primaryDashboard).toBeNull()
        await expectLogic(logic).toDispatchActions(['loadPrimaryDashboardResponseSuccess'])
        expect(logic.values.primaryDashboard?.id).toBe(8)
    })
})
