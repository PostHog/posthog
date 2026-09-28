import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { InsightModel, SavedInsightsTabs } from '~/types'

import { InsightRow } from './InsightRow'
import { trendingInsightsLogic } from './trendingInsightsLogic'

export function Trending(): JSX.Element {
    const { trendingInsights, trendingInsightsLoading, trendingInsightsLoadedError, expandedInsightIds } =
        useValues(trendingInsightsLogic)
    const { toggleInsightExpanded, loadTrendingInsights } = useActions(trendingInsightsLogic)

    return (
        <CompactList
            title={
                <div className="flex items-center gap-1">
                    Trending
                    <Tooltip title="Trending insights have the most unique views in the last 7 days.">
                        <IconInfo className="text-muted text-base" />
                    </Tooltip>
                </div>
            }
            viewAllURL={urls.savedInsights(SavedInsightsTabs.All)}
            viewAllDataAttr="insights-home-tab-trending-view-all"
            loading={trendingInsightsLoading}
            error={trendingInsightsLoadedError}
            errorMessage={{
                title: "Couldn't load trending insights",
                description: 'Something went wrong loading this list.',
                buttonText: 'Retry',
                buttonOnClick: loadTrendingInsights,
            }}
            emptyMessage={{
                title: 'No trending insights',
                description: 'Frequently viewed insights will appear here.',
                buttonText: 'View all insights',
                buttonTo: urls.savedInsights(SavedInsightsTabs.All),
            }}
            items={trendingInsights.slice(0, 5)}
            renderRow={(insight: InsightModel) => (
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
