import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { InsightRow } from './InsightRow'
import { trendingInsightsLogic } from './trendingInsightsLogic'

export function Trending(): JSX.Element {
    const { trendingInsights, trendingInsightsLoading, expandedInsightIds } = useValues(trendingInsightsLogic)
    const { toggleInsightExpanded } = useActions(trendingInsightsLogic)

    return (
        <CompactList
            title={
                <div className="flex items-center gap-1">
                    Trending
                    <Tooltip title="Trending insights are calculated based on the number of unique views in the last 7 days.">
                        <IconInfo className="text-muted text-base" />
                    </Tooltip>
                </div>
            }
            viewAllURL={urls.savedInsights(SavedInsightsTabs.All)}
            viewAllDataAttr="insights-home-tab-trending-view-all"
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
