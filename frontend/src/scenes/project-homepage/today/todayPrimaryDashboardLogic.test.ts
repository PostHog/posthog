import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { todayLogic } from './todayLogic'
import { todayPrimaryDashboardLogic } from './todayPrimaryDashboardLogic'

describe('todayPrimaryDashboardLogic', () => {
    it.each([
        { name: 'shows the project dashboard', useSampleData: false, expected: 7 },
        { name: 'hides the project dashboard in sample mode', useSampleData: true, expected: null },
    ])('$name', ({ useSampleData, expected }) => {
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, primary_dashboard: 7 })
        const logic = todayPrimaryDashboardLogic()
        logic.mount()
        todayLogic.actions.setUseSampleData(useSampleData)

        expect(logic.values.primaryDashboardId).toBe(expected)
    })
})
