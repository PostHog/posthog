import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { getRecommendedProducts } from '../productRecommendations'
import { useCaseSelectionLogic } from './useCaseSelectionLogic'

describe('useCaseSelectionLogic', () => {
    let logic: ReturnType<typeof useCaseSelectionLogic.build>

    beforeEach(() => {
        useMocks({})
        initKeaTests()
        logic = useCaseSelectionLogic()
        logic.mount()
        // Mock window.posthog
        window.posthog = {
            capture: jest.fn(),
        } as any
    })

    afterEach(() => {
        delete (window as any).posthog
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

            expect(window.posthog.capture).toHaveBeenCalledWith('onboarding_use_case_selected', {
                use_case: 'fix_issues',
                recommended_products: getRecommendedProducts('fix_issues'),
            })
        })

        it('handles pick_myself use case', async () => {
            await expectLogic(logic, () => {
                logic.actions.selectUseCase('pick_myself')
            })

            expect(router.values.location.pathname).toContain('/products')
            expect(router.values.searchParams.useCase).toBe('pick_myself')
            expect(window.posthog.capture).toHaveBeenCalledWith('onboarding_use_case_selected', {
                use_case: 'pick_myself',
                recommended_products: [],
            })
        })

        it('handles different use cases', async () => {
            const useCases: Array<
                'see_user_behavior' | 'fix_issues' | 'launch_features' | 'collect_feedback' | 'monitor_ai'
            > = ['see_user_behavior', 'fix_issues', 'launch_features', 'collect_feedback', 'monitor_ai']

            for (const useCase of useCases) {
                await expectLogic(logic, () => {
                    logic.actions.selectUseCase(useCase)
                })

                expect(router.values.searchParams.useCase).toBe(useCase)
                expect(window.posthog.capture).toHaveBeenCalledWith(
                    'onboarding_use_case_selected',
                    expect.objectContaining({
                        use_case: useCase,
                    })
                )
            }
        })
    })
})
