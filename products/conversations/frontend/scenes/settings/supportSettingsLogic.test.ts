import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { supportSettingsLogic } from './supportSettingsLogic'

describe('supportSettingsLogic', () => {
    let logic: ReturnType<typeof supportSettingsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                'api/conversations/v1/email/status': { configs: [] },
            },
            post: {
                'api/environments/:team_id/': async ({ request }) => [200, await request.json()],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('aiSuggestionsEnabled selector', () => {
        it.each([
            ['conversations_settings is undefined', undefined, false],
            ['ai_suggestions_enabled is not set', { widget_enabled: true }, false],
            ['ai_suggestions_enabled is true', { ai_suggestions_enabled: true }, true],
        ])('%s', async (_label, settings, expected) => {
            if (settings) {
                initKeaTests(true, { conversations_settings: settings } as unknown as TeamType)
            }
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({ aiSuggestionsEnabled: expected })
        })
    })

    describe('setAiSuggestionsEnabled', () => {
        it('sets loading state and dispatches updateCurrentTeam', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setAiSuggestionsEnabled(true)
            })
                .toDispatchActions(['setAiSuggestionsLoading', 'updateCurrentTeam'])
                .toMatchValues({ aiSuggestionsLoading: true })
        })

        it('clears loading state on updateCurrentTeamSuccess', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            logic.actions.setAiSuggestionsLoading(true)
            expect(logic.values.aiSuggestionsLoading).toBe(true)

            logic.actions.updateCurrentTeamSuccess({} as TeamType)
            expect(logic.values.aiSuggestionsLoading).toBe(false)
        })

        it('clears loading state on updateCurrentTeamFailure', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            logic.actions.setAiSuggestionsLoading(true)
            expect(logic.values.aiSuggestionsLoading).toBe(true)

            logic.actions.updateCurrentTeamFailure('update failed')
            expect(logic.values.aiSuggestionsLoading).toBe(false)
        })
    })
})
