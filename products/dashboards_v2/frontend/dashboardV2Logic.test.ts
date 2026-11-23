import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { dashboardV2Logic } from './dashboardV2Logic'

describe('dashboardV2Logic access', () => {
    it.each([
        [AccessControlLevel.Viewer, 1],
        [AccessControlLevel.Editor, 2],
    ])('with %s access, adding a tab leaves %i tabs', (level, tabs) => {
        initKeaTests()
        const logic = dashboardV2Logic()
        logic.mount()
        logic.actions.commitDashboard({
            ...logic.values.dashboard,
            user_access_level: level,
            tabs: logic.values.dashboard.tabs.slice(0, 1),
        })

        logic.actions.applyDashboardEdit({ edit: 'addTab', title: 'Another' })

        expect(logic.values.dashboard.tabs).toHaveLength(tabs)
    })
})
