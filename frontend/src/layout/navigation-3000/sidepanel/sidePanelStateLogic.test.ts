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

    it('does not leave a #panel=max hash in the URL when opening Max', async () => {
        await expectLogic(logic, () => {
            logic.actions.openSidePanel(SidePanelTab.Max)
        }).toFinishAllListeners()
        // No lingering hash means a reload / return to the app won't auto-reopen Max
        expect(router.values.hashParams).not.toHaveProperty('panel')
    })

    it('clears the #panel=max:options hash after consuming options', async () => {
        await expectLogic(logic, () => {
            logic.actions.openSidePanel(SidePanelTab.Max, '!Explain this insight')
        }).toFinishAllListeners()
        // Options live in kea state, not the URL, so reload doesn't re-run the prompt
        expect(logic.values.selectedTabOptions).toEqual('!Explain this insight')
        expect(router.values.hashParams).not.toHaveProperty('panel')
    })

    it('opens Max from a #panel=max hash but then strips it', async () => {
        await expectLogic(logic, () => {
            router.actions.push('', {}, { panel: 'max' })
        }).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })
        expect(router.values.hashParams).not.toHaveProperty('panel')
    })

    it('keeps the #panel hash in the URL for tabs that persist it (e.g. Support)', async () => {
        await expectLogic(logic, () => {
            logic.actions.openSidePanel(SidePanelTab.Support, 'bug:analytics')
        }).toFinishAllListeners()
        expect(router.values.hashParams['panel']).toEqual('support:bug:analytics')

        // Closing removes the hash
        await expectLogic(logic, () => {
            logic.actions.closeSidePanel()
        }).toFinishAllListeners()
        expect(router.values.hashParams).not.toHaveProperty('panel')
    })
})
