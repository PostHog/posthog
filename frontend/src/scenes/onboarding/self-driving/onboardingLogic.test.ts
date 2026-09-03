import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { onboardingLogic } from './onboardingLogic'
import { useCaseSelectionLogic } from './useCaseSelectionLogic'

describe('onboardingLogic', () => {
    let logic: ReturnType<typeof onboardingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/user_product_list': async () => [200, { results: [], count: 0 }],
            },
            patch: {
                '/api/environments/:team_id/': async ({ request }) => [
                    200,
                    { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as Record<string, unknown>) },
                ],
                '/api/environments/:team_id/add_product_intent/': async () => [200, { product_intents: [] }],
                '/api/environments/:team_id/complete_product_onboarding': async () => [200, { product_intents: [] }],
            },
        })
        initKeaTests()
        logic = onboardingLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('persists both onboarding completion signals', async () => {
        await expectLogic(logic, () => {
            logic.actions.completeOnboarding()
        }).toDispatchActions([
            (action) => {
                if (action.type !== logic.actionTypes.updateCurrentTeam) {
                    return false
                }
                if (!action.payload.completed_snippet_onboarding) {
                    return false
                }
                expect(action.payload).toMatchObject({
                    completed_snippet_onboarding: true,
                    has_completed_onboarding_for: { [ProductKey.PRODUCT_ANALYTICS]: true },
                })
                return true
            },
        ])
    })

    it('short-circuits when a completion is already in flight', async () => {
        logic.actions.setIsCompleting(true)
        await expectLogic(logic, () => {
            logic.actions.completeOnboarding()
        }).toNotHaveDispatchedActions(['updateCurrentTeam'])
    })

    it('sets the selected tools required options before completing onboarding', async () => {
        const updates: Record<string, unknown>[] = []
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            session_recording_masking_config: null,
        })
        useMocks({
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const update = (await request.json()) as Record<string, unknown>
                    updates.push(update)
                    return [200, { ...MOCK_DEFAULT_TEAM, ...update }]
                },
            },
        })

        await logic.asyncActions.completeOnboarding('find_problems')

        expect(updates).toEqual(
            expect.arrayContaining([
                {
                    autocapture_exceptions_opt_in: true,
                },
                {
                    session_recording_opt_in: true,
                    session_recording_masking_config: { maskAllInputs: true },
                    capture_console_log_opt_in: true,
                    capture_performance_opt_in: true,
                },
            ])
        )
    })

    it('records each selected product once and persists completion last', async () => {
        let addIntentRequests = 0
        let customProductLoads = 0
        const intents: { intent_context: ProductIntentContext; product_type: ProductKey }[] = []
        const writes: string[] = []
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, surveys_opt_in: true })
        useMocks({
            get: {
                '/api/environments/:team_id/user_product_list': () => {
                    customProductLoads++
                    return [200, { results: [], count: 0 }]
                },
            },
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const update = (await request.json()) as Record<string, unknown>
                    if (update.completed_snippet_onboarding) {
                        writes.push('completion')
                    }
                    return [200, { ...MOCK_DEFAULT_TEAM, ...update }]
                },
                '/api/environments/:team_id/add_product_intent/': () => {
                    addIntentRequests++
                    return [200, { product_intents: [] }]
                },
                '/api/environments/:team_id/complete_product_onboarding': async ({ request }) => {
                    const intent = (await request.json()) as {
                        intent_context: ProductIntentContext
                        product_type: ProductKey
                    }
                    intents.push(intent)
                    writes.push(`intent:${intent.product_type}`)
                    return [200, { ...MOCK_DEFAULT_TEAM, product_intents: [] }]
                },
            },
        })
        useCaseSelectionLogic.actions.selectUseCase('find_problems')

        await logic.asyncActions.completeOnboarding('find_problems')

        expect(addIntentRequests).toBe(0)
        expect(intents).toHaveLength(6)
        expect(new Set(intents.map(({ product_type }) => product_type)).size).toBe(6)
        expect(intents).not.toContainEqual(expect.objectContaining({ product_type: ProductKey.SURVEYS }))
        expect(intents).toEqual(
            expect.arrayContaining([
                {
                    product_type: ProductKey.ERROR_TRACKING,
                    intent_context: ProductIntentContext.ONBOARDING_PRODUCT_SELECTED_PRIMARY,
                },
                {
                    product_type: ProductKey.SESSION_REPLAY,
                    intent_context: ProductIntentContext.ONBOARDING_PRODUCT_SELECTED_SECONDARY,
                },
                {
                    product_type: ProductKey.CONVERSATIONS,
                    intent_context: ProductIntentContext.ONBOARDING_PRODUCT_SELECTED_SECONDARY,
                },
            ])
        )
        expect(customProductLoads).toBe(1)
        expect(writes.at(-1)).toBe('completion')
        expect(useCaseSelectionLogic.values.selectedUseCase).toBeNull()
    })

    it('reports onboarding completion once with the shared event schema', async () => {
        const capture = jest.spyOn(posthog, 'capture')

        await logic.asyncActions.completeOnboarding('find_problems')

        expect(capture.mock.calls.filter(([event]) => event === 'onboarding completed')).toEqual([
            [
                'onboarding completed',
                {
                    product_key: ProductKey.ERROR_TRACKING,
                    version: 2,
                    flow_variant: 'context_first',
                },
            ],
        ])
        capture.mockRestore()
    })

    it('does not persist completion when a product intent request fails', async () => {
        let completionUpdates = 0
        silenceKeaLoadersErrors()
        useMocks({
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const update = (await request.json()) as Record<string, unknown>
                    if (update.completed_snippet_onboarding) {
                        completionUpdates++
                    }
                    return [200, { ...MOCK_DEFAULT_TEAM, ...update }]
                },
                '/api/environments/:team_id/complete_product_onboarding': () => [500, {}],
            },
        })

        try {
            await logic.asyncActions.completeOnboarding('find_problems')
            expect(completionUpdates).toBe(0)
        } finally {
            resumeKeaLoadersErrors()
        }
    })
})
