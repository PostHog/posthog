import { actions, connect, kea, listeners, path } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/types'

import type { productsLogicType } from './productsLogicType'

export const productsLogic = kea<productsLogicType>([
    path(() => ['scenes', 'products', 'productsLogic']),
    connect({
        actions: [teamLogic, ['updateCurrentTeam'], onboardingLogic, ['setProduct']],
        values: [userLogic, ['user']],
    }),
    actions(() => ({
        onSelectProduct: (product: ProductKey) => ({ product }),
    })),
    listeners(({ actions, values }) => ({
        onSelectProduct: ({ product }) => {
            const includeFirstOnboardingProductOnUserProperties = values.user?.date_joined
                ? new Date(values.user?.date_joined) > new Date('2024-01-10T00:00:00Z')
                : false
            eventUsageLogic.actions.reportOnboardingProductSelected(
                product,
                includeFirstOnboardingProductOnUserProperties
            )

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
