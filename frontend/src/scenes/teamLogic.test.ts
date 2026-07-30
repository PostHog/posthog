import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AppContext, TeamType } from '~/types'

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
                    // Only /api/projects is mocked: a name-only update must not hit the
                    // deprecated /api/environments endpoint
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
                logic.actions.updateCurrentTeam({ name: 'Renamed project' })
            }).toDispatchActions([projectLogic.actionTypes.loadCurrentProjectSuccess, 'updateCurrentTeamSuccess'])

            expect(logic.values.currentTeam?.name).toBe('Renamed project')
            expect(projectLogic.values.currentProject?.name).toBe('Renamed project')
        })
    })

    describe('product intent loaders', () => {
        beforeEach(() => {
            initKeaTests()
            useMocks({
                get: {
                    '/api/environments/:id/user_product_list': () => [200, { results: [], count: 0 }],
                },
                patch: {
                    // Simulates the race hit in production: `complete_product_onboarding` serializes
                    // the team from a snapshot taken before the concurrent onboarding-completion
                    // PATCH committed, so its response arrives without the completion fields.
                    '/api/environments/:id/complete_product_onboarding': () => [
                        200,
                        {
                            ...MOCK_DEFAULT_TEAM,
                            completed_snippet_onboarding: false,
                            has_completed_onboarding_for: {},
                            product_intents: [{ product_type: 'session_replay' }],
                        },
                    ],
                },
            })
            logic = teamLogic()
            logic.mount()
        })

        it('keeps onboarding-completion fields when a stale team snapshot comes back', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentTeamSuccess'])

            await expectLogic(logic, () => {
                logic.actions.recordProductIntentOnboardingComplete({ product_type: ProductKey.SESSION_REPLAY })
            }).toDispatchActions(['recordProductIntentOnboardingCompleteSuccess'])

            // Fresh local fields survive; only product_intents is taken from the response.
            // A wholesale replace here would flip hasOnboardedAnyProduct back to false and
            // send the user into the /onboarding redirect loop.
            expect(logic.values.currentTeam?.completed_snippet_onboarding).toBe(true)
            expect(logic.values.currentTeam?.has_completed_onboarding_for).toEqual({ product_analytics: true })
            expect(logic.values.hasOnboardedAnyProduct).toBe(true)
            expect((logic.values.currentTeam as TeamType)?.product_intents).toEqual([
                { product_type: 'session_replay' },
            ])
        })

        it('ignores a response for a different team (team switched mid-flight)', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentTeamSuccess'])
            useMocks({
                patch: {
                    '/api/environments/:id/complete_product_onboarding': () => [
                        200,
                        {
                            ...MOCK_DEFAULT_TEAM,
                            id: MOCK_TEAM_ID + 1,
                            product_intents: [{ product_type: 'surveys' }],
                        },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.recordProductIntentOnboardingComplete({ product_type: ProductKey.SURVEYS })
            }).toDispatchActions(['recordProductIntentOnboardingCompleteSuccess'])

            // The stale team's intents must not be grafted onto the team that is now active.
            expect(logic.values.currentTeam?.id).toBe(MOCK_TEAM_ID)
            expect((logic.values.currentTeam as TeamType)?.product_intents).toBeUndefined()
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
