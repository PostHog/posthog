import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from './sidePanelStateLogic'

describe('sidePanelStateLogic - onSceneTabChanged', () => {
    let logic: ReturnType<typeof sidePanelStateLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UX_REMOVE_SIDEPANEL]: true })
        logic = sidePanelStateLogic.build()
        logic.mount()
    })

    it('does not run when UX_REMOVE_SIDEPANEL flag is disabled', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UX_REMOVE_SIDEPANEL]: false })

        logic.actions.openSidePanel(SidePanelTab.Max)
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })

        logic.actions.onSceneTabChanged('tab-a', 'tab-b')
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })
    })

    it('does not crash when featureFlagLogic is not mounted', async () => {
        featureFlagLogic.unmount()

        logic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.onSceneTabChanged('tab-a', 'tab-b')

        await expectLogic(logic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })
    })

    it('saves and restores side panel state when switching between tabs', async () => {
        // Open panel on tab-a
        logic.actions.openSidePanel(SidePanelTab.Max)
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })

        // Switch to tab-b: saves tab-a state, tab-b has no saved state so panel stays as-is
        logic.actions.onSceneTabChanged('tab-a', 'tab-b')
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true })

        // Close panel on tab-b
        logic.actions.closeSidePanel()
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false })

        // Switch back to tab-a: restores open state
        logic.actions.onSceneTabChanged('tab-b', 'tab-a')
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })
    })

    it('restores closed state for tabs that were explicitly closed', async () => {
        // Open panel on tab-a
        logic.actions.openSidePanel(SidePanelTab.Max)

        // Switch to tab-b
        logic.actions.onSceneTabChanged('tab-a', 'tab-b')

        // Close panel on tab-b, then switch to tab-c
        logic.actions.closeSidePanel()
        logic.actions.onSceneTabChanged('tab-b', 'tab-c')

        // Switch back to tab-b: should restore the closed state
        logic.actions.onSceneTabChanged('tab-c', 'tab-b')
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false })
    })

    it('preserves current state for never-visited tabs', async () => {
        // Open panel
        logic.actions.openSidePanel(SidePanelTab.Max)
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true })

        // Switch to a brand-new tab: no saved state, should preserve current panel state
        logic.actions.onSceneTabChanged('tab-a', 'tab-new')
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })
    })

    it('restores selectedTabOptions along with the tab', async () => {
        logic.actions.openSidePanel(SidePanelTab.Support, 'bug:analytics')
        await expectLogic(logic).toMatchValues({
            sidePanelOpen: true,
            selectedTab: SidePanelTab.Support,
            selectedTabOptions: 'bug:analytics',
        })

        // Switch away and back
        logic.actions.onSceneTabChanged('tab-a', 'tab-b')
        logic.actions.closeSidePanel()
        logic.actions.onSceneTabChanged('tab-b', 'tab-a')

        await expectLogic(logic).toMatchValues({
            sidePanelOpen: true,
            selectedTab: SidePanelTab.Support,
            selectedTabOptions: 'bug:analytics',
        })
    })

    it('deduplicates identical transitions from activateTab and setScene', async () => {
        logic.actions.openSidePanel(SidePanelTab.Max)

        // First dispatch (from activateTab): saves tab-a state, tab-b has no saved state
        logic.actions.onSceneTabChanged('tab-a', 'tab-b')
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true })

        // Close the panel on tab-b
        logic.actions.closeSidePanel()
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false })

        // Second dispatch (from setScene) with same transition: should be skipped
        // If it weren't skipped, it would overwrite tab-a's saved state with {open: false}
        logic.actions.onSceneTabChanged('tab-a', 'tab-b')
        await expectLogic(logic).toMatchValues({ sidePanelOpen: false })

        // Switch back to tab-a: should still have the original open state
        logic.actions.onSceneTabChanged('tab-b', 'tab-a')
        await expectLogic(logic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })
    })
})
