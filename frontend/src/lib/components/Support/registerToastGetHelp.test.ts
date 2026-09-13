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

    const setUp = ({ cloud, sidePanelAvailable }: { cloud: boolean; sidePanelAvailable: boolean }): void => {
        // sidePanelStateLogic reflects open state in the URL hash, which initKeaTests doesn't reset.
        window.history.replaceState(null, '', '/')
        initKeaTests()
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(sidePanelAvailable)
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
        setUp({ cloud: true, sidePanelAvailable: true })

        await expectLogic(sidePanelStateLogic, () => getHelp()).toFinishAllListeners()

        expect(router.values.hashParams['panel']).toBe(SidePanelTab.Support)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Support)
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(windowOpen).not.toHaveBeenCalled()
        // The panel replaces the URL rather than pushing it. A pushed entry would leave Back stripping
        // the hash while the panel stayed open, so Back would do nothing a person can see.
        await expectLogic(router).toNotHaveDispatchedActions(['push'])
    })

    // Self-hosted has no Support tab, and a scene without a panel falls through to the support modal,
    // which asks every plan for a message. Both link out to the channels their plan actually has.
    it.each([
        ['a self-hosted instance', { cloud: false, sidePanelAvailable: true }],
        ['a scene without a side panel', { cloud: true, sidePanelAvailable: false }],
    ])('sends %s to the support options docs', async (_, options) => {
        setUp(options)

        await expectLogic(sidePanelStateLogic, () => getHelp()).toFinishAllListeners()

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(windowOpen).toHaveBeenCalledWith(
            expect.stringContaining('posthog.com/docs/support-options'),
            '_blank',
            'noopener'
        )
    })
})
