import { actions, connect, kea, listeners, path } from 'kea'
import { router } from 'kea-router'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { UseCaseOption, getRecommendedProducts } from '../productRecommendations'
import type { useCaseSelectionLogicType } from './useCaseSelectionLogicType'

export const useCaseSelectionLogic = kea<useCaseSelectionLogicType>([
    path(['scenes', 'onboarding', 'useCaseSelectionLogic']),
    connect({
        actions: [eventUsageLogic, ['reportOnboardingUseCaseSelected']],
    }),

    actions({
        selectUseCase: (useCase: UseCaseOption) => ({ useCase }),
    }),

    listeners(({ actions }) => ({
        selectUseCase: ({ useCase }: { useCase: UseCaseOption }) => {
            if (useCase !== 'pick_myself') {
                actions.reportOnboardingUseCaseSelected(useCase, getRecommendedProducts(useCase))
            }

            router.actions.push(urls.products(), { useCase })
        },
    })),
])
