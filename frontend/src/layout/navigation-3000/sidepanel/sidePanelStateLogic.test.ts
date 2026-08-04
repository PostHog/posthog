import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

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

    it('opens from a #panel= hash already in the URL when the logic first mounts (cold load)', async () => {
        // A hard refresh or a pasted deep link has the hash present before this logic ever mounts, so its
        // "previous" location (as far as kea-router's synthetic initial dispatch is concerned) is
        // indistinguishable from the current one. That must not be mistaken for a stale, carried-over hash.
        router.actions.replace('/settings/user', {}, { panel: 'discussion' })
        const coldLogic = sidePanelStateLogic.build()
        coldLogic.mount()
        await expectLogic(coldLogic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Discussion })
    })
})
