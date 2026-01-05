import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { getRecommendedProducts } from '../productRecommendations'
import { useCaseSelectionLogic } from './useCaseSelectionLogic'

describe('useCaseSelectionLogic', () => {
    let logic: ReturnType<typeof useCaseSelectionLogic.build>

    beforeEach(() => {
        useMocks({})
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        logic = useCaseSelectionLogic()
        logic.mount()
        // Clear mocks after mount to ignore the 'onboarding started' event
        jest.clearAllMocks()
    })

    describe('selectUseCase', () => {
        it('navigates to products page with useCase param', async () => {
            await expectLogic(logic, () => {
                logic.actions.selectUseCase('see_user_behavior')
            })

            expect(router.values.location.pathname).toContain('/products')
            expect(router.values.searchParams.useCase).toBe('see_user_behavior')
        })

        it('captures analytics event with use case and recommended products', async () => {
            await expectLogic(logic, () => {
                logic.actions.selectUseCase('fix_issues')
            })
                .toDispatchActions(eventUsageLogic, ['reportOnboardingUseCaseSelected'])
                .toFinishListeners()

            await expectLogic(eventUsageLogic).toFinishListeners()

            expect(posthog.capture).toHaveBeenCalledWith('onboarding use case selected', {
                use_case: 'fix_issues',
                recommended_products: getRecommendedProducts('fix_issues'),
            })
        })

        it('handles pick_myself use case', async () => {
            await expectLogic(logic, () => {
                logic.actions.selectUseCase('pick_myself')
            })
                .toDispatchActions(eventUsageLogic, ['reportOnboardingUseCaseSkipped'])
                .toFinishListeners()

            await expectLogic(eventUsageLogic).toFinishListeners()

            expect(router.values.location.pathname).toContain('/products')
            expect(router.values.searchParams.useCase).toBe('pick_myself')
            // pick_myself should NOT trigger the 'use case selected' event, but should trigger 'use case skipped'
            expect(posthog.capture).toHaveBeenCalledWith('onboarding use case skipped')
            expect(posthog.capture).not.toHaveBeenCalledWith('onboarding use case selected', expect.anything())
        })

        it('handles different use cases', async () => {
            const useCases: Array<
                'see_user_behavior' | 'fix_issues' | 'launch_features' | 'collect_feedback' | 'monitor_ai'
            > = ['see_user_behavior', 'fix_issues', 'launch_features', 'collect_feedback', 'monitor_ai']

            for (const useCase of useCases) {
                jest.clearAllMocks()

                await expectLogic(logic, () => {
                    logic.actions.selectUseCase(useCase)
                })
                    .toDispatchActions(eventUsageLogic, ['reportOnboardingUseCaseSelected'])
                    .toFinishListeners()

                await expectLogic(eventUsageLogic).toFinishListeners()

                expect(router.values.searchParams.useCase).toBe(useCase)
                expect(posthog.capture).toHaveBeenCalledWith(
                    'onboarding use case selected',
                    expect.objectContaining({
                        use_case: useCase,
                    })
                )
            }
        })
    })
})
