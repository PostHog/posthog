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

    describe('renaming the project', () => {
        let projectPatchBody: { name?: string } | null

        beforeEach(() => {
            initKeaTests()
            projectPatchBody = null
            useMocks({
                patch: {
                    '/api/environments/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, any>
                        return [200, { ...MOCK_DEFAULT_TEAM, ...body }]
                    },
                    '/api/projects/:id/': async ({ request }) => {
                        projectPatchBody = (await request.json()) as { name?: string }
                        return [200, { ...MOCK_DEFAULT_PROJECT, ...projectPatchBody }]
                    },
                },
            })
            logic = teamLogic()
            logic.mount()
        })

        it('writes the new name to the project and refreshes it in-session', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentTeamSuccess'])

            logic.actions.updateCurrentTeam({ name: 'Renamed project' })
            await expectLogic(logic).toDispatchActions(['updateCurrentTeamSuccess'])

            // The Project.name write must fire (it was silently skipped when currentProject was unloaded)
            expect(projectPatchBody).toEqual({ name: 'Renamed project' })
            // and projectLogic.currentProject must reflect it so the switcher/breadcrumbs update in-session
            expect(projectLogic.values.currentProject?.name).toBe('Renamed project')
        })
    })
})
