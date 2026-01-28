import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

import { CustomerAnalyticsQueryCard } from 'products/customer_analytics/frontend/components/CustomerAnalyticsQueryCard'
import {
    InsightDefinition,
    customerAnalyticsSceneLogic,
} from 'products/customer_analytics/frontend/customerAnalyticsSceneLogic'

export function SessionInsights(): JSX.Element {
    const { sessionInsights, tabId } = useValues(customerAnalyticsSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <h2 className="mb-0 ml-1">Session insights</h2>
                {featureFlags[FEATURE_FLAGS.SESSIONS_EXPLORER] && (
                    <LemonButton
                        size="small"
                        noPadding
                        targetBlank
                        to={urls.activity(ActivityTab.ExploreSessions)}
                        tooltip="Open session explorer"
                    />
                )}
            </div>
            <div className="grid grid-cols-3 gap-2">
                {sessionInsights.map((insight, index) => {
                    return (
                        <CustomerAnalyticsQueryCard key={index} insight={insight as InsightDefinition} tabId={tabId} />
                    )
                })}
            </div>
        </div>
    )
}
