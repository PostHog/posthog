import { expectLogic } from 'kea-test-utils'
import { toast } from 'react-toastify'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { mcpHintLogic } from './mcpHintLogic'

// Stub the toast so rendering it can't throw; the hint's observable signal is the recordShown
// action it dispatches when (and only when) a toast is shown.
jest.mock('react-toastify', () => ({
    toast: { info: jest.fn(), dismiss: jest.fn() },
}))

describe('mcpHintLogic', () => {
    let logic: ReturnType<typeof mcpHintLogic.build>

    beforeEach(() => {
        initKeaTests()
        // The 7-day cooldown and per-surface dismissals persist to localStorage; clear it before
        // mounting so each case starts from a clean slate rather than inheriting the prior one.
        localStorage.clear()
        logic = mcpHintLogic()
        logic.mount()
        ;(toast.info as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic?.unmount()
    })

    async function openMaxSidePanel(): Promise<void> {
        // sidePanelOpen is flipped by a listener, so let it settle before reading isMaxOpen.
        await expectLogic(sidePanelStateLogic, () => {
            sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max)
        }).toFinishAllListeners()
    }

    it('shows the cohort hint when Max is not open', async () => {
        await expectLogic(logic, () => {
            logic.actions.tryShowHint('cohorts.create')
        }).toDispatchActions(['recordShown'])
    })

    it('suppresses the cohort hint when the Max side panel is open', async () => {
        await openMaxSidePanel()
        await expectLogic(logic, () => {
            logic.actions.tryShowHint('cohorts.create')
        })
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['recordShown'])
    })

    it('still shows a Max-supported surface hint while Max is open', async () => {
        await openMaxSidePanel()
        await expectLogic(logic, () => {
            logic.actions.tryShowHint('insights.create')
        }).toDispatchActions(['recordShown'])
    })

    it('shows the cohort hint when a non-Max side panel is open', async () => {
        await expectLogic(sidePanelStateLogic, () => {
            sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.tryShowHint('cohorts.create')
        }).toDispatchActions(['recordShown'])
    })
})
