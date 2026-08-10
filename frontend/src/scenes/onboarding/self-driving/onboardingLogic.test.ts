import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { onboardingLogic } from './onboardingLogic'

describe('onboardingLogic', () => {
    let logic: ReturnType<typeof onboardingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
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
                    session_recording_opt_in: true,
                    autocapture_exceptions_opt_in: true,
                },
                {
                    session_recording_masking_config: { maskAllInputs: true },
                    capture_console_log_opt_in: true,
                    capture_performance_opt_in: true,
                },
            ])
        )
    })

    it('registers the selected use case primary and secondary intents when onboarding completes', async () => {
        const intents: { intent_context: ProductIntentContext; product_type: ProductKey }[] = []
        useMocks({
            patch: {
                '/api/environments/:team_id/': async ({ request }) => [
                    200,
                    { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as Record<string, unknown>) },
                ],
                '/api/environments/:team_id/add_product_intent/': async ({ request }) => {
                    intents.push(
                        (await request.json()) as { intent_context: ProductIntentContext; product_type: ProductKey }
                    )
                    return [200, { product_intents: [] }]
                },
                '/api/environments/:team_id/complete_product_onboarding': async () => [200, { product_intents: [] }],
            },
        })

        await logic.asyncActions.completeOnboarding('find_problems')

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
    })
})
