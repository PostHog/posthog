import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { CustomerAnalyticsEventStream } from '../EventStream/CustomerAnalyticsEventStream'
import { CustomerAnalyticsTaskDigest } from './CustomerAnalyticsTaskDigest'

export function CustomerAnalyticsNotifications(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const showTaskDigest = featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]
    const showEventStream = featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]

    return (
        <div className="flex flex-col gap-8">
            {showTaskDigest && (
                <section>
                    <h3>Task digest emails</h3>
                    <CustomerAnalyticsTaskDigest />
                </section>
            )}
            {showEventStream && (
                <section>
                    <h3>Event stream</h3>
                    <CustomerAnalyticsEventStream />
                </section>
            )}
            {!showTaskDigest && !showEventStream && (
                <LemonBanner type="info">
                    Notifications are available with customer tasks or the customer event stream.
                </LemonBanner>
            )}
        </div>
    )
}
