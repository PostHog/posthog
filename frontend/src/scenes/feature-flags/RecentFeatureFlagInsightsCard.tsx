import { useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { InsightRow } from 'scenes/project-homepage/RecentInsights'
import { urls } from 'scenes/urls'
import { InsightModel } from '~/types'
import { featureFlagLogic } from './featureFlagLogic'

export function RecentFeatureFlagInsights(): JSX.Element {
    const { recentInsights, recentInsightsLoading, featureFlag } = useValues(featureFlagLogic)
    return (
        <CompactList
            title="Insights that use this feature flag"
            loading={recentInsightsLoading}
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
            items={recentInsights.slice(0, 5)}
            renderRow={(insight: InsightModel, index) => <InsightRow key={index} insight={insight} />}
        />
    )
}
