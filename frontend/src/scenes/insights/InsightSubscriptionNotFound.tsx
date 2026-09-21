import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { urls } from 'scenes/urls'

import { InsightSkeleton } from './InsightSkeleton'
import { insightSubscriptionNotFoundLogic } from './insightSubscriptionNotFoundLogic'

export function InsightSubscriptionNotFound({
    insightShortId,
    subscriptionId,
}: {
    insightShortId: string
    subscriptionId: number
}): JSX.Element {
    const { subscriptionAvailable, subscriptionAvailableLoading } = useValues(
        insightSubscriptionNotFoundLogic({ insightShortId, subscriptionId })
    )

    if (subscriptionAvailableLoading) {
        return <InsightSkeleton />
    }

    return (
        <div className="flex flex-col items-center">
            <NotFound
                object="insight"
                caption={
                    subscriptionAvailable ? (
                        <>
                            This subscription still exists, but its insight is unavailable. The insight may have been
                            deleted or its access settings changed.
                            <br />
                            Subscriptions do not send reports for deleted insights.
                        </>
                    ) : undefined
                }
            />
            {subscriptionAvailable && (
                <LemonButton type="primary" to={urls.subscription(subscriptionId)} className="mt-4">
                    Open subscription
                </LemonButton>
            )}
        </div>
    )
}
