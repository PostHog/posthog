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

    it('unlocks the card when a later team update replaces the enable request', async () => {
        logic.actions.pickChannel('email', 'needs-setup', false)
        teamLogic.actions.updateCurrentTeam({ timezone: 'Europe/Brussels' })

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pendingChannel).toBeNull()
        expect(router.values.location.pathname).not.toContain('/support/settings')
    })
})
