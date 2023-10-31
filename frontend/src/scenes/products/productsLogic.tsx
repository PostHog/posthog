import { kea, path, actions, listeners } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { ProductKey } from '~/types'

import type { productsLogicType } from './productsLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export const productsLogic = kea<productsLogicType>([
    path(() => ['scenes', 'products', 'productsLogic']),
    actions(() => ({
        onSelectProduct: (product: ProductKey) => ({ product }),
    })),
    listeners(() => ({
        onSelectProduct: ({ product }) => {
            eventUsageLogic.actions.reportOnboardingProductSelected(product)

            switch (product) {
                case ProductKey.PRODUCT_ANALYTICS:
                    return
                case ProductKey.SESSION_REPLAY:
                    teamLogic.actions.updateCurrentTeam({
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
