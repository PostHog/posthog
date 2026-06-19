import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from './sidePanelStateLogic'

describe('sidePanelStateLogic', () => {
    let logic: ReturnType<typeof sidePanelStateLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        logic = sidePanelStateLogic.build()
        logic.mount()
        jest.spyOn(posthog, 'capture').mockClear()
    })

    it('starts closed', async () => {
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false, selectedTab: null })
    })

    it('opens only on an explicit openSidePanel trigger', async () => {
        logic.actions.openSidePanel(SidePanelTab.Max)
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })
    })

    it('carries selectedTabOptions when opening', async () => {
        logic.actions.openSidePanel(SidePanelTab.Activity, 'bug:analytics')
        await expectLogic(logic).toMatchValues({
            sidePanelOpen: true,
            selectedTab: SidePanelTab.Activity,
            selectedTabOptions: 'bug:analytics',
        })
    })

    it('closes when closeSidePanel is called with no tab', async () => {
        logic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.closeSidePanel()
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false })
    })

    it('only closes for the currently selected tab when a tab is passed', async () => {
        logic.actions.openSidePanel(SidePanelTab.Max)

        // Closing a different tab leaves the panel open
        logic.actions.closeSidePanel(SidePanelTab.Activity)
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true })

        // Closing the selected tab closes the panel
        logic.actions.closeSidePanel(SidePanelTab.Max)
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false })
    })

    it("does not emit 'sidebar closed' when the panel is already closed", async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')

        // Repeated no-op closes (e.g. from resizer/layout flicker) must not emit events
        logic.actions.closeSidePanel()
        logic.actions.closeSidePanel()
        logic.actions.closeSidePanel(SidePanelTab.Max)
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false })

        expect(captureSpy).not.toHaveBeenCalledWith('sidebar closed', expect.anything())
    })

    it("emits 'sidebar closed' only once per genuine open→closed transition", async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')

        logic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.closeSidePanel()
        // A second close while already closed must be a no-op for analytics
        logic.actions.closeSidePanel()
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false })

        expect(captureSpy.mock.calls.filter(([event]) => event === 'sidebar closed')).toHaveLength(1)
    })
})
