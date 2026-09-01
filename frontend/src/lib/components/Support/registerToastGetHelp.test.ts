import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { getHelp, resetGetHelpAction } from 'lib/lemon-ui/LemonToast/getHelp'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { registerToastGetHelp } from './registerToastGetHelp'

describe('registerToastGetHelp', () => {
    beforeEach(() => {
        // sidePanelStateLogic reflects open state in the URL hash, which initKeaTests doesn't reset.
        window.history.replaceState(null, '', '/')
        initKeaTests()
        sidePanelStateLogic.mount()
    })

    afterEach(() => {
        resetGetHelpAction()
    })

    it('opens the support side panel instead of leaving the app', async () => {
        registerToastGetHelp()

        await expectLogic(sidePanelStateLogic, () => getHelp()).toFinishAllListeners()

        expect(router.values.hashParams['panel']).toBe(SidePanelTab.Support)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Support)
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
    })
})
