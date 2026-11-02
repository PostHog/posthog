import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { sidepanelTicketsLogic } from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'
import { ConversationTicket } from 'products/conversations/frontend/types'

import { todayContextPanelLogic } from './todayContextPanelLogic'

describe('todayContextPanelLogic', () => {
    let logic: ReturnType<typeof todayContextPanelLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = todayContextPanelLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('reads the Support tab URL without mounting the tickets logic, because mounting it fetches tickets', () => {
        logic.actions.openSidePanel(SidePanelTab.Support)

        expect(sidepanelTicketsLogic.findMounted()).toBeNull()
        expect(logic.values.fullScreenUrl).toBeNull()

        const unmountTickets = sidepanelTicketsLogic.mount()
        sidepanelTicketsLogic.actions.setTickets([
            { id: 't1', status: 'open', message_count: 1, created_at: '2026-07-13T00:00:00Z' } as ConversationTicket,
        ])
        expect(logic.values.fullScreenUrl).toBe(urls.myTickets())
        unmountTickets()
    })

    it('keeps the floating button away until the user undocks the panel', () => {
        expect(logic.values.launcherHidden).toBe(true)

        logic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.undock()
        expect(logic.values.launcherHidden).toBe(false)

        logic.actions.setFloatingOpen(false)
        expect(logic.values.launcherHidden).toBe(false)
    })

    it.each([
        ['docks the panel', (): void => logic.actions.dock()],
        ['dismisses the button', (): void => logic.actions.hideLauncher()],
    ])('takes the floating button away again once the user %s', (_, takeAway) => {
        logic.actions.openSidePanel(SidePanelTab.Max)
        logic.actions.undock()
        logic.actions.setFloatingOpen(false)
        takeAway()
        if (logic.values.docked) {
            logic.actions.closeSidePanel()
        }

        expect(logic.values.launcherHidden).toBe(true)
    })
})
