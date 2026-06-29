import { toast } from 'react-toastify'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { mcpHintLogic } from './mcpHintLogic'

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

    it('shows the cohort hint when Max is not open', () => {
        logic.actions.tryShowHint('cohorts.create')
        expect(toast.info).toHaveBeenCalledTimes(1)
    })

    it('suppresses the cohort hint when the Max side panel is open', () => {
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.tryShowHint('cohorts.create')
        expect(toast.info).not.toHaveBeenCalled()
    })

    it('still shows a Max-supported surface hint while Max is open', () => {
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.tryShowHint('insights.create')
        expect(toast.info).toHaveBeenCalledTimes(1)
    })

    it('shows the cohort hint when a non-Max side panel is open', () => {
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)
        logic.actions.tryShowHint('cohorts.create')
        expect(toast.info).toHaveBeenCalledTimes(1)
    })
})
