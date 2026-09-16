import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import * as classicEmbed from '../classicEmbedContext'
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

    it.each([
        [false, SidePanelTab.Max, true],
        [true, SidePanelTab.Max, false],
        [true, SidePanelTab.Info, true],
        [true, SidePanelTab.Activity, true],
    ])('opens an explicit panel with Classic %s, tab %s, open %s', async (classic, tab, open) => {
        const context = jest.replaceProperty(
            classicEmbed,
            'classicEmbedContext',
            classic ? { parentOrigin: 'https://us.posthog.com', projectId: '1' } : null
        )
        try {
            logic.actions.openSidePanel(tab)
            await expectLogic(logic).toMatchValues({ sidePanelOpen: open, selectedTab: tab })
        } finally {
            context.restore()
        }
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
})
