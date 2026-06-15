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
                'api/environments/:team_id/': (req: any) => [200, req.body],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('aiSuggestionsEnabled selector', () => {
        it('returns false when conversations_settings is undefined', async () => {
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({ aiSuggestionsEnabled: false })
        })

        it('returns false when ai_suggestions_enabled is not set', async () => {
            const team = { conversations_settings: { widget_enabled: true } } as unknown as TeamType
            initKeaTests(true, team)
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({ aiSuggestionsEnabled: false })
        })

        it('returns true when ai_suggestions_enabled is true', async () => {
            const team = {
                conversations_settings: { ai_suggestions_enabled: true },
            } as unknown as TeamType
            initKeaTests(true, team)
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({ aiSuggestionsEnabled: true })
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
