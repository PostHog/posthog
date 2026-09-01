import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { getHelp, resetGetHelpAction } from 'lib/lemon-ui/LemonToast/getHelp'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { PreflightStatus, SidePanelTab } from '~/types'

import { registerToastGetHelp } from './registerToastGetHelp'

describe('registerToastGetHelp', () => {
    const windowOpen = jest.fn()

    const setUp = (cloud: boolean): void => {
        // sidePanelStateLogic reflects open state in the URL hash, which initKeaTests doesn't reset.
        window.history.replaceState(null, '', '/')
        initKeaTests()
        sidePanelStateLogic.mount()
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ cloud } as PreflightStatus)
        registerToastGetHelp()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        window.open = windowOpen
    })

    afterEach(() => {
        resetGetHelpAction()
    })

    it('opens the support side panel on cloud instead of leaving the app', async () => {
        setUp(true)

        await expectLogic(sidePanelStateLogic, () => getHelp()).toFinishAllListeners()

        expect(router.values.hashParams['panel']).toBe(SidePanelTab.Support)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Support)
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(windowOpen).not.toHaveBeenCalled()
    })

    // A self-hosted instance has no support panel, so opening one would leave the person with nothing.
    it('sends self-hosted instances to the support page', async () => {
        setUp(false)

        await expectLogic(sidePanelStateLogic, () => getHelp()).toFinishAllListeners()

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(windowOpen).toHaveBeenCalledWith(expect.stringContaining('posthog.com/support'), '_blank')
    })
})
