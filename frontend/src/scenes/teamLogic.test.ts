import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { teamLogic } from './teamLogic'

describe('teamLogic', () => {
    let logic: ReturnType<typeof teamLogic.build>

    describe('when team is loaded', () => {
        beforeEach(() => {
            initKeaTests()
            logic = teamLogic()
            logic.mount()
        })

        it('currentTeamIdStrict returns the team id', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentTeamSuccess'])
            expect(logic.values.currentTeamIdStrict).toBe(MOCK_TEAM_ID)
        })

        it('currentProjectId returns the project id', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentTeamSuccess'])
            expect(logic.values.currentProjectId).toBe(MOCK_DEFAULT_TEAM.project_id)
        })
    })

    describe('before team is loaded', () => {
        beforeEach(() => {
            initKeaTests(false)
            // Clear team context after initKeaTests so currentTeam starts as null
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                current_team: undefined,
            } as unknown as AppContext
            logic = teamLogic()
            logic.mount()
        })

        it('currentTeamIdStrict throws', () => {
            expect(() => logic.values.currentTeamIdStrict).toThrow('accessed before')
        })

        it('currentProjectId throws', () => {
            expect(() => logic.values.currentProjectId).toThrow('accessed before')
        })

        it('currentTeamId returns null (non-breaking)', () => {
            expect(logic.values.currentTeamId).toBeNull()
        })
    })
})
