import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { projectLogic } from './projectLogic'
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

    describe('updateCurrentTeam with a name-only payload', () => {
        beforeEach(() => {
            initKeaTests(false)
            // Simulate projectLogic not having loaded yet, as the rename must not depend on it
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                current_project: undefined,
            } as unknown as AppContext
            useMocks({
                get: {
                    '/api/projects/@current': () => [500, {}],
                },
                patch: {
                    '/api/environments/:id': async ({ request }) => [
                        200,
                        { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as Record<string, any>) },
                    ],
                    '/api/projects/:id': async ({ request }) => [
                        200,
                        { ...MOCK_DEFAULT_PROJECT, ...((await request.json()) as Record<string, any>) },
                    ],
                },
            })
            logic = teamLogic()
            logic.mount()
        })

        it('renames the parent project and syncs it into projectLogic', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentTeamSuccess'])
            expect(projectLogic.values.currentProject).toBeNull()

            await expectLogic(logic, () => {
                logic.actions.updateCurrentTeam({ name: 'Compliance Dashboard Prod' })
            }).toDispatchActions([projectLogic.actionTypes.loadCurrentProjectSuccess, 'updateCurrentTeamSuccess'])

            expect(logic.values.currentTeam?.name).toBe('Compliance Dashboard Prod')
            expect(projectLogic.values.currentProject?.name).toBe('Compliance Dashboard Prod')
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

        it('currentTeamIdStrict returns @current fallback', () => {
            expect(logic.values.currentTeamIdStrict).toBe('@current')
        })

        it('currentProjectId returns @current fallback', () => {
            expect(logic.values.currentProjectId).toBe('@current')
        })

        it('currentTeamId returns null (non-breaking)', () => {
            expect(logic.values.currentTeamId).toBeNull()
        })
    })
})
