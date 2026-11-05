import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { DEFAULT_SIDEBAR_CARD_LAYOUT, SidebarCardLayout } from './ticketSidebarLayout'
import { ticketSidebarLayoutLogic } from './ticketSidebarLayoutLogic'

describe('ticketSidebarLayoutLogic', () => {
    let logic: ReturnType<typeof ticketSidebarLayoutLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        teamLogic.mount()
        teamLogic.actions.setTeam({
            id: 99,
            conversations_settings: {},
        } as any)

        logic = ticketSidebarLayoutLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        teamLogic.unmount()
        jest.restoreAllMocks()
    })

    it('mounts with default layout when no user or team layout is set', () => {
        expectLogic(logic).toMatchValues({
            userLayout: null,
            teamLayout: null,
            hasUserOverride: false,
            isCustomized: false,
            effectiveLayout: DEFAULT_SIDEBAR_CARD_LAYOUT,
        })
    })

    it('uses team layout when no user override exists', async () => {
        const customTeamLayout: SidebarCardLayout = [
            { id: 'status', visible: true },
            { id: 'priority', visible: false },
            { id: 'customer', visible: true },
        ]

        teamLogic.actions.setTeam({
            id: 99,
            conversations_settings: {
                ticket_sidebar_card_layout: customTeamLayout,
            },
        } as any)

        await expectLogic(logic).toMatchValues({
            hasUserOverride: false,
            teamLayout: expect.arrayContaining([{ id: 'status', visible: true }]),
        })

        expect(logic.values.effectiveLayout[0].id).toBe('status')
        expect(logic.values.effectiveLayout[1].id).toBe('priority')
    })

    it('lets user preference override team layout', async () => {
        const teamLayout: SidebarCardLayout = [
            { id: 'status', visible: true },
            { id: 'priority', visible: true },
        ]
        teamLogic.actions.setTeam({
            id: 99,
            conversations_settings: { ticket_sidebar_card_layout: teamLayout },
        } as any)

        const userLayout: SidebarCardLayout = [
            { id: 'customer', visible: true },
            { id: 'sla', visible: false },
        ]
        localStorage.setItem(
            'posthog-conversations-ticket-sidebar-card-layout-99',
            JSON.stringify(userLayout)
        )

        logic.actions.loadUserLayout()

        await expectLogic(logic).toMatchValues({
            hasUserOverride: true,
        })
        expect(logic.values.effectiveLayout[0].id).toBe('customer')
        expect(logic.values.effectiveLayout[1].id).toBe('sla')
        expect(logic.values.effectiveLayout[1].visible).toBe(false)
    })

    it('toggles row visibility in draft and saves to user preference', async () => {
        logic.actions.setLayoutModalOpen(true)
        logic.actions.toggleDraftRowVisibility('status')

        expect(posthog.capture).toHaveBeenCalledWith(
            'ticket_sidebar_row_visibility_toggled',
            expect.objectContaining({ row_id: 'status', visible: false })
        )

        logic.actions.saveDraftLayout()

        await expectLogic(logic).toMatchValues({
            isLayoutModalOpen: false,
            hasUserOverride: true,
        })
        expect(logic.values.effectiveLayout.find((r) => r.id === 'status')?.visible).toBe(false)
        expect(posthog.capture).toHaveBeenCalledWith(
            'ticket_sidebar_layout_updated',
            expect.objectContaining({
                hidden_rows: expect.arrayContaining(['status']),
            })
        )
    })

    it('moves row in draft and saves new order', async () => {
        logic.actions.setLayoutModalOpen(true)
        logic.actions.moveDraftRow(0, 1)

        expect(posthog.capture).toHaveBeenCalledWith('ticket_sidebar_layout_reordered', expect.anything())

        logic.actions.saveDraftLayout()

        expect(logic.values.effectiveLayout[0].id).toBe('created')
        expect(logic.values.effectiveLayout[1].id).toBe('customer')
    })

    it('resets user override back to default', async () => {
        const userLayout: SidebarCardLayout = [{ id: 'tags', visible: true }]
        localStorage.setItem(
            'posthog-conversations-ticket-sidebar-card-layout-99',
            JSON.stringify(userLayout)
        )
        logic.actions.loadUserLayout()

        expect(logic.values.hasUserOverride).toBe(true)

        logic.actions.resetUserLayout()

        await expectLogic(logic).toMatchValues({
            userLayout: null,
            hasUserOverride: false,
            effectiveLayout: DEFAULT_SIDEBAR_CARD_LAYOUT,
        })
        expect(posthog.capture).toHaveBeenCalledWith('ticket_sidebar_layout_reset', { team_id: 99 })
    })

    it('saves current layout as team default', () => {
        const spy = jest.spyOn(teamLogic.actions, 'updateCurrentTeam')
        logic.actions.setLayoutModalOpen(true)
        logic.actions.toggleDraftRowVisibility('snooze')
        logic.actions.saveAsTeamDefault()

        expect(spy).toHaveBeenCalledWith(
            expect.objectContaining({
                conversations_settings: expect.objectContaining({
                    ticket_sidebar_card_layout: expect.arrayContaining([
                        expect.objectContaining({ id: 'snooze', visible: false }),
                    ]),
                }),
            })
        )
        expect(posthog.capture).toHaveBeenCalledWith(
            'ticket_sidebar_layout_saved_as_team_default',
            expect.objectContaining({ team_id: 99 })
        )
    })
})
