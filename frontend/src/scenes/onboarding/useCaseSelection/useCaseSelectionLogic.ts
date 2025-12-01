import { actions, afterMount, connect, kea, listeners, path } from 'kea'
import { router } from 'kea-router'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { UseCaseOption, getRecommendedProducts } from '../productRecommendations'
import type { useCaseSelectionLogicType } from './useCaseSelectionLogicType'

export const useCaseSelectionLogic = kea<useCaseSelectionLogicType>([
    path(['scenes', 'onboarding', 'useCaseSelectionLogic']),
    connect({
        actions: [
            eventUsageLogic,
            ['reportOnboardingUseCaseSelected', 'reportOnboardingStarted', 'reportOnboardingUseCaseSkipped'],
        ],
    }),

    actions({
        selectUseCase: (useCase: UseCaseOption) => ({ useCase }),
    }),

    listeners(({ actions }) => ({
        selectUseCase: ({ useCase }: { useCase: UseCaseOption }) => {
            if (useCase === 'pick_myself') {
                actions.reportOnboardingUseCaseSkipped()
            } else {
                actions.reportOnboardingUseCaseSelected(useCase, getRecommendedProducts(useCase))
            }

            router.actions.push(urls.products(), { useCase })
        },
    })),

    afterMount(({ actions }) => {
        actions.reportOnboardingStarted('use_case_selection')
    }),
])
