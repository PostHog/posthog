import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { Heading, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { CustomerAnalyticsEventStream } from '../EventStream/CustomerAnalyticsEventStream'
import { CustomerAnalyticsTaskDigest } from './CustomerAnalyticsTaskDigest'

export function CustomerAnalyticsNotifications(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const showTaskDigest = featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]
    const showEventStream = featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-8">
                {showTaskDigest && (
                    <section className="flex flex-col gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Task digest emails
                        </Heading>
                        <CustomerAnalyticsTaskDigest />
                    </section>
                )}
                {showEventStream && (
                    <section className="flex flex-col gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Event stream
                        </Heading>
                        <CustomerAnalyticsEventStream />
                    </section>
                )}
                {!showTaskDigest && !showEventStream && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Notifications are available with customer tasks or the customer event stream.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
            </div>
        )
    }

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
