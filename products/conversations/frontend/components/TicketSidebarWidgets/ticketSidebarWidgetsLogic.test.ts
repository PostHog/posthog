import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { TicketSidebarConfiguration, UserUIConfiguration } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { TICKET_SIDEBAR_WIDGETS, resolveTicketSidebarLayout } from './ticketSidebarLayout'
import { ticketSidebarWidgetsLogic } from './ticketSidebarWidgetsLogic'

const ALL_KEYS = TICKET_SIDEBAR_WIDGETS.map((widget) => widget.key)

describe('ticketSidebarWidgetsLogic', () => {
    let mountedLogic: ReturnType<typeof ticketSidebarWidgetsLogic.build> | undefined
    let patchedUser: Partial<UserType> | null

    function setUp(uiConfiguration: UserUIConfiguration | null): ReturnType<typeof ticketSidebarWidgetsLogic.build> {
        initKeaTests()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, ui_configuration: uiConfiguration })
        mountedLogic = ticketSidebarWidgetsLogic()
        mountedLogic.mount()
        return mountedLogic
    }

    beforeEach(() => {
        patchedUser = null
        useMocks({
            patch: {
                '/api/users/@me/': async ({ request }) => {
                    patchedUser = (await request.json()) as Partial<UserType>
                    return [200, { ...MOCK_DEFAULT_USER, ...patchedUser }]
                },
            },
        })
    })

    afterEach(() => {
        mountedLogic?.unmount()
        mountedLogic = undefined
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
        expect(resolveTicketSidebarLayout(stored as TicketSidebarConfiguration | null)).toEqual({ visible, hidden })
    })

    it('shows edits only once saved to the account, and drops them on cancel', async () => {
        const logic = setUp(null)

        logic.actions.startEditing()
        logic.actions.hideWidget('ai_triage')
        logic.actions.moveWidget(logic.values.layout.visible.indexOf('activity'), 0)
        logic.actions.cancelEditing()

        await expectLogic(logic).toMatchValues({ isEditing: false, userLayout: null })
        expect(logic.values.layout.visible).toEqual(ALL_KEYS)
        expect(patchedUser).toBeNull()

        await expectLogic(logic, () => {
            logic.actions.startEditing()
            logic.actions.hideWidget('ai_triage')
            logic.actions.moveWidget(logic.values.layout.visible.indexOf('activity'), 0)
            logic.actions.saveLayout()
        }).toFinishAllListeners()

        const visible = ['activity', ...ALL_KEYS.filter((key) => key !== 'activity' && key !== 'ai_triage')]
        expect(patchedUser?.ui_configuration).toEqual({
            version: 1,
            ticket_sidebar: { order: [...visible, 'ai_triage'], hidden: ['ai_triage'] },
        })
        expect(logic.values.isEditing).toBe(false)
        expect(logic.values.layout).toEqual({ visible, hidden: ['ai_triage'] })
    })

    it('saving the default clears the stored layout and keeps the other UI settings', async () => {
        const logic = setUp({
            version: 1,
            sql_editor: { vim_mode_enabled: true },
            ticket_sidebar: { hidden: ['exceptions'] },
        })

        await expectLogic(logic, () => {
            logic.actions.startEditing()
            logic.actions.resetDraftToDefault()
            logic.actions.saveLayout()
        }).toFinishAllListeners()

        expect(patchedUser?.ui_configuration).toEqual({ version: 1, sql_editor: { vim_mode_enabled: true } })
        expect(logic.values.userLayout).toBeNull()
    })
})
