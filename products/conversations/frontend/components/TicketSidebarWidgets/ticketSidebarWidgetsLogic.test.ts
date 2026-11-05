import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { StoredTicketSidebarLayout, TICKET_SIDEBAR_WIDGETS, resolveTicketSidebarLayout } from './ticketSidebarLayout'
import { ticketSidebarWidgetsLogic } from './ticketSidebarWidgetsLogic'

const ALL_KEYS = TICKET_SIDEBAR_WIDGETS.map((widget) => widget.key)

describe('ticketSidebarWidgetsLogic', () => {
    let logic: ReturnType<typeof ticketSidebarWidgetsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = ticketSidebarWidgetsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    test.each([
        ['no saved layout shows every widget in default order', null, ALL_KEYS, []],
        [
            'a widget missing from an older saved layout still shows',
            { order: ['activity', 'ai_triage'], hidden: ['ai_triage'] },
            ['activity', ...ALL_KEYS.filter((key) => key !== 'activity' && key !== 'ai_triage')],
            ['ai_triage'],
        ],
        [
            'unknown and repeated keys are ignored',
            { order: ['removed_widget', 'exceptions', 'exceptions'], hidden: ['removed_widget'] },
            ['exceptions', ...ALL_KEYS.filter((key) => key !== 'exceptions')],
            [],
        ],
    ])('resolving a stored layout: %s', (_name, stored, visible, hidden) => {
        expect(resolveTicketSidebarLayout(stored as StoredTicketSidebarLayout | null)).toEqual({ visible, hidden })
    })

    it('shows edits only once saved, and drops them on cancel', async () => {
        logic.actions.startEditing()
        logic.actions.hideWidget('ai_triage')
        logic.actions.moveWidget(logic.values.layout.visible.indexOf('activity'), 0)
        logic.actions.cancelEditing()

        await expectLogic(logic).toMatchValues({ isEditing: false, userLayout: null })
        expect(logic.values.layout.visible).toEqual(ALL_KEYS)

        logic.actions.startEditing()
        logic.actions.hideWidget('ai_triage')
        logic.actions.moveWidget(logic.values.layout.visible.indexOf('activity'), 0)
        logic.actions.saveLayout()

        await expectLogic(logic).toMatchValues({ isEditing: false })
        expect(logic.values.layout).toEqual({
            visible: ['activity', ...ALL_KEYS.filter((key) => key !== 'activity' && key !== 'ai_triage')],
            hidden: ['ai_triage'],
        })
    })

    it('stores nothing when the default is saved, so later changes to the default apply', () => {
        logic.actions.setUserLayout({ order: [], hidden: ['exceptions'] })
        logic.actions.startEditing()
        logic.actions.resetDraftToDefault()
        logic.actions.saveLayout()

        expect(logic.values.userLayout).toBeNull()
    })
})
