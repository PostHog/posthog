import { useActions, useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { InsightRow } from './InsightRow'
import { trendingInsightsLogic } from './trendingInsightsLogic'

export function Trending(): JSX.Element {
    const { trendingInsights, trendingInsightsLoading, expandedInsightIds } = useValues(trendingInsightsLogic)
    const { toggleInsightExpanded } = useActions(trendingInsightsLogic)

    return (
        <CompactList
            title="Trending"
            viewAllURL={urls.savedInsights(SavedInsightsTabs.All)}
            loading={trendingInsightsLoading}
            emptyMessage={{
                title: 'No trending insights',
                description: 'Insights that are viewed frequently in your organization will appear here.',
                buttonText: 'View all insights',
                buttonTo: urls.savedInsights(SavedInsightsTabs.All),
            }}
            items={trendingInsights.slice(0, 5)}
            renderRow={(insight: QueryBasedInsightModel) => (
                <InsightRow
                    key={insight.short_id}
                    insight={insight}
                    isExpanded={expandedInsightIds.has(insight.short_id)}
                    onToggle={() => toggleInsightExpanded(insight.short_id)}
                    dataAttr="trending-insight-item"
                />
            )}
            contentHeightBehavior="fit-content"
        />
    )
}
