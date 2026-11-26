import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import type { Dashboard } from './dashboard/dashboardTypes'
import { dashboardV2Logic } from './dashboardV2Logic'

type Logic = ReturnType<typeof dashboardV2Logic.build>

const addTab = (logic: Logic): void => logic.actions.applyDashboardEdit({ edit: 'addTab', title: 'Another' })
const openTwoTabBoard = (logic: Logic): void =>
    logic.actions.openDashboard({
        ...logic.values.dashboard,
        tabs: [
            { ...logic.values.dashboard.tabs[0], id: 'imported-1' },
            { ...logic.values.dashboard.tabs[0], id: 'imported-2' },
        ],
    } as Dashboard)

describe('dashboardV2Logic', () => {
    it.each([
        ['adding a tab', AccessControlLevel.Viewer, 1, addTab],
        ['adding a tab', AccessControlLevel.Editor, 2, addTab],
        ['opening another board', AccessControlLevel.Viewer, 1, openTwoTabBoard],
        ['opening another board', AccessControlLevel.Editor, 2, openTwoTabBoard],
    ])('%s with %s access leaves %i tabs', (_, level, tabs, change) => {
        initKeaTests()
        const logic = dashboardV2Logic()
        logic.mount()
        logic.actions.commitDashboard({
            ...logic.values.dashboard,
            user_access_level: level,
            tabs: logic.values.dashboard.tabs.slice(0, 1),
        })

        change(logic)

        expect(logic.values.dashboard.tabs).toHaveLength(tabs)
    })

    it('undoing an opened board goes back to the tab that was showing', () => {
        initKeaTests()
        const logic = dashboardV2Logic()
        logic.mount()
        logic.actions.commitDashboard({ ...logic.values.dashboard, user_access_level: AccessControlLevel.Editor })
        addTab(logic)
        const shownTab = logic.values.activeTab.id
        expect(shownTab).not.toEqual(logic.values.dashboard.tabs[0].id)

        openTwoTabBoard(logic)
        logic.actions.setActiveTab('imported-2')
        logic.actions.undo()
        expect(logic.values.activeTabId).toEqual(shownTab)

        logic.actions.redo()
        expect(logic.values.activeTabId).toEqual('imported-2')
    })
})
