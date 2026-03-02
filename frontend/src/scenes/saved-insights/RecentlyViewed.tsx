import { useActions, useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { projectHomepageLogic } from '../project-homepage/projectHomepageLogic'
import { InsightRow } from './InsightRow'

export function RecentlyViewed(): JSX.Element {
    const { recentInsights, recentInsightsLoading, expandedInsightIds } = useValues(projectHomepageLogic)
    const { loadRecentInsights, toggleInsightExpanded } = useActions(projectHomepageLogic)
    useOnMountEffect(loadRecentInsights)

    return (
        <CompactList
            title="Recently viewed"
            viewAllURL={urls.savedInsights(SavedInsightsTabs.All)}
            loading={recentInsightsLoading}
            emptyMessage={{
                title: 'You have no recently viewed insights',
                description: "Explore this project's insights by clicking below.",
                buttonText: 'View insights',
                buttonTo: urls.savedInsights(),
            }}
            items={recentInsights.slice(0, 5)}
            renderRow={(insight: QueryBasedInsightModel) => (
                <InsightRow
                    key={insight.short_id}
                    insight={insight}
                    isExpanded={expandedInsightIds.has(insight.short_id)}
                    onToggle={() => toggleInsightExpanded(insight.short_id)}
                    dataAttr="recently-viewed-insight-item"
                />
            )}
            contentHeightBehavior="fit-content"
        />
    )
}
