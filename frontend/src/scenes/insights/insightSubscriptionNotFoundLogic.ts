import { MakeLogicType, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { subscriptionsRetrieve } from 'products/subscriptions/frontend/generated/api'

interface InsightSubscriptionNotFoundProps {
    insightShortId: string
    subscriptionId: number
}

export type insightSubscriptionNotFoundLogicType = MakeLogicType<
    { subscriptionAvailable: boolean; subscriptionAvailableLoading: boolean },
    { loadSubscriptionAvailable: () => void },
    InsightSubscriptionNotFoundProps
>

export const insightSubscriptionNotFoundLogic = kea<insightSubscriptionNotFoundLogicType>([
    path(['scenes', 'insights', 'insightSubscriptionNotFoundLogic']),
    props({} as InsightSubscriptionNotFoundProps),
    key(({ insightShortId, subscriptionId }) => `${insightShortId}-${subscriptionId}`),
    loaders(({ props }) => ({
        subscriptionAvailable: [
            false,
            {
                loadSubscriptionAvailable: async (): Promise<boolean> => {
                    try {
                        const subscription = await subscriptionsRetrieve(
                            String(getCurrentTeamId()),
                            props.subscriptionId
                        )
                        return !subscription.deleted && subscription.insight_short_id === props.insightShortId
                    } catch {
                        return false
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => actions.loadSubscriptionAvailable()),
])
