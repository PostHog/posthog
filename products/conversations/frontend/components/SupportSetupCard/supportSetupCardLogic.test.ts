import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { supportSetupCardLogic } from './supportSetupCardLogic'

describe('supportSetupCardLogic', () => {
    let logic: ReturnType<typeof supportSetupCardLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:id/conversations/tickets/send_test/': [201, { id: 'ticket-uuid', ticket_number: 7 }],
            },
            patch: {
                '/api/projects/:id': async ({ request }) => [
                    200,
                    {
                        ...MOCK_DEFAULT_TEAM,
                        conversations_enabled: false,
                        ...((await request.json()) as Record<string, any>),
                    },
                ],
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_enabled: false } as TeamType)
        logic = supportSetupCardLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('turns Support on, then opens the picked channel in Support settings', async () => {
        logic.actions.pickChannel('email', 'needs-setup', false)
        expect(logic.values.pendingChannel).toBe('email')

        await expectLogic(logic).toFinishAllListeners()

        expect(teamLogic.values.currentTeam?.conversations_enabled).toBe(true)
        expect(router.values.location.pathname).toContain('/support/settings')
        expect(router.values.hashParams).toEqual({ channel: 'email' })
        expect(logic.values.pendingChannel).toBeNull()
    })

    it('turns Support and the widget on in place, without leaving the setup screen', async () => {
        logic.actions.pickChannel('widget', 'needs-setup', false)

        await expectLogic(logic).toFinishAllListeners()

        expect(teamLogic.values.currentTeam?.conversations_enabled).toBe(true)
        expect(teamLogic.values.currentTeam?.conversations_settings?.widget_enabled).toBe(true)
        expect(router.values.location.pathname).not.toContain('/support/settings')
        expect(logic.values.pendingChannel).toBeNull()
    })

    it('turns Support on, then opens the picked import in Support settings', async () => {
        logic.actions.pickImport('zendesk', 'needs-setup', false)
        expect(logic.values.pendingReason).toBe('Turning Support on…')

        await expectLogic(logic).toFinishAllListeners()

        expect(teamLogic.values.currentTeam?.conversations_enabled).toBe(true)
        expect(router.values.location.pathname).toContain('/support/settings')
        expect(router.values.hashParams).toEqual({ selectedSetting: 'conversations-imports', import: 'zendesk' })
        expect(logic.values.pendingImport).toBeNull()
    })

    it('opens the test ticket after it is created', async () => {
        logic.actions.sendTestTicket()

        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toContain('/support/tickets/7')
    })

    it('unlocks the card when a later team update replaces the enable request', async () => {
        logic.actions.pickChannel('email', 'needs-setup', false)
        teamLogic.actions.updateCurrentTeam({ timezone: 'Europe/Brussels' })

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pendingChannel).toBeNull()
        expect(router.values.location.pathname).not.toContain('/support/settings')
    })
})
