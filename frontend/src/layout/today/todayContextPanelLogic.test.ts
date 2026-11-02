import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { todayContextPanelLogic } from './todayContextPanelLogic'

describe('todayContextPanelLogic', () => {
    let logic: ReturnType<typeof todayContextPanelLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = todayContextPanelLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps the floating button away until the user undocks the panel', () => {
        expect(logic.values.launcherHidden).toBe(true)

        logic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.undock()
        expect(logic.values.launcherHidden).toBe(false)

        logic.actions.setFloatingOpen(false)
        expect(logic.values.launcherHidden).toBe(false)
    })

    it.each([
        ['docks the panel', (): void => logic.actions.dock()],
        ['dismisses the button', (): void => logic.actions.hideLauncher()],
    ])('takes the floating button away again once the user %s', (_, takeAway) => {
        logic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.undock()
        logic.actions.setFloatingOpen(false)
        takeAway()
        if (logic.values.docked) {
            logic.actions.closeSidePanel()
        }

        expect(logic.values.launcherHidden).toBe(true)
    })
})
