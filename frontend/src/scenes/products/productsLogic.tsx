import { kea, path, actions, listeners, connect } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { ProductKey } from '~/types'

import type { productsLogicType } from './productsLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'

export const productsLogic = kea<productsLogicType>([
    path(() => ['scenes', 'products', 'productsLogic']),
    connect({
        actions: [teamLogic, ['updateCurrentTeam'], onboardingLogic, ['setProduct']],
    }),
    actions(() => ({
        onSelectProduct: (product: ProductKey) => ({ product }),
    })),
    listeners(({ actions }) => ({
        onSelectProduct: ({ product }) => {
            eventUsageLogic.actions.reportOnboardingProductSelected(product)

            switch (product) {
                case ProductKey.PRODUCT_ANALYTICS:
                    return
                case ProductKey.SESSION_REPLAY:
                    actions.updateCurrentTeam({
                        session_recording_opt_in: true,
                        capture_console_log_opt_in: true,
                        capture_performance_opt_in: true,
                    })
                    return
                case ProductKey.FEATURE_FLAGS:
                    return
                default:
                    return
            }
        },
    })),
])
