import { useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { InsightRow } from 'scenes/project-homepage/RecentInsights'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'

export function RecentFeatureFlagInsights(): JSX.Element {
    const { relatedInsights, relatedInsightsLoading, featureFlag } = useValues(featureFlagLogic)
    return (
        <CompactList
            title="Insights that use this feature flag"
            loading={relatedInsightsLoading}
            emptyMessage={{
                title: 'You have no insights that use this feature flag',
                description: "Explore this feature flag's insights by creating one below.",
                buttonText: 'Create insight',
                buttonTo: urls.insightNew({
                    events: [{ id: '$pageview', name: '$pageview', type: 'events', math: 'dau' }],
                    breakdown_type: 'event',
                    breakdown: `$feature/${featureFlag.key}`,
                }),
            }}
            items={relatedInsights.slice(0, 5)}
            renderRow={(insight: QueryBasedInsightModel, index) => <InsightRow key={index} insight={insight} />}
        />
    )
}
