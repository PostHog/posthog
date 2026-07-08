import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { subscriptionsList } from '@posthog/products-subscriptions/frontend/generated/api'

import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { subscriptionCountLogicType } from './subscriptionCountLogicType'

export const subscriptionCountLogic = kea<subscriptionCountLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionCountLogic']),
    loaders({
        // null = not loaded yet; consumers treat null as "unknown" and fail open.
        subscriptionCount: [
            null as number | null,
            {
                loadSubscriptionCount: async (): Promise<number> => {
                    // limit=1 keeps the payload tiny; `count` reflects the full team total.
                    const response = await subscriptionsList(String(getCurrentTeamId()), { limit: 1 })
                    return response.count ?? 0
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSubscriptionCount()
    }),
])
