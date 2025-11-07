import { actions, kea, listeners, path } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { UseCaseOption, getRecommendedProducts } from '../productRecommendations'
import type { useCaseSelectionLogicType } from './useCaseSelectionLogicType'

export const useCaseSelectionLogic = kea<useCaseSelectionLogicType>([
    path(['scenes', 'onboarding', 'useCaseSelectionLogic']),

    actions({
        selectUseCase: (useCase: UseCaseOption) => ({ useCase }),
    }),

    listeners(() => ({
        selectUseCase: ({ useCase }: { useCase: UseCaseOption }) => {
            // Track analytics
            if (window.posthog) {
                window.posthog.capture('onboarding_use_case_selected', {
                    use_case: useCase,
                    recommended_products: getRecommendedProducts(useCase),
                })
            }

            // Navigate with URL param - no API call needed!
            router.actions.push(urls.products() + `?useCase=${useCase}`)
        },
    })),
])
