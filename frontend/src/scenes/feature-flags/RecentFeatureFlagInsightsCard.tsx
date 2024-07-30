import { useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { InsightRow } from 'scenes/project-homepage/RecentInsights'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind } from '~/queries/schema'
import { BaseMathType, QueryBasedInsightModel } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'

export function RecentFeatureFlagInsights(): JSX.Element {
    const { relatedInsights, relatedInsightsLoading, featureFlag } = useValues(featureFlagLogic)
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                { event: '$pageview', name: '$pageview', kind: NodeKind.EventsNode, math: BaseMathType.UniqueUsers },
            ],
            breakdownFilter: {
                breakdown_type: 'event',
                breakdown: `$feature/${featureFlag.key}`,
            },
        },
    }
    return (
        <CompactList
            title="Insights that use this feature flag"
            loading={relatedInsightsLoading}
            emptyMessage={{
                title: 'You have no insights that use this feature flag',
                description: "Explore this feature flag's insights by creating one below.",
                buttonText: 'Create insight',
                buttonTo: urls.insightNew(undefined, undefined, query),
            }}
            items={relatedInsights.slice(0, 5)}
            renderRow={(insight: QueryBasedInsightModel, index) => <InsightRow key={index} insight={insight} />}
        />
    )
}
