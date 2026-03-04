import { useActions, useValues } from 'kea'

import { IconDashboard, IconExternal } from '@posthog/icons'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { DashboardBasicType, QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { projectHomepageLogic } from '../project-homepage/projectHomepageLogic'
import { InsightRow } from './InsightRow'

type RecentItem = (QueryBasedInsightModel & { itemType: 'insight' }) | (DashboardBasicType & { itemType: 'dashboard' })

export function RecentlyViewed(): JSX.Element {
    const { recentInsights, recentInsightsLoading, expandedInsightIds, recentDashboards } =
        useValues(projectHomepageLogic)
    const { loadRecentInsights, toggleInsightExpanded } = useActions(projectHomepageLogic)
    useOnMountEffect(loadRecentInsights)

    const items: RecentItem[] = [
        ...recentInsights.map((i) => ({ ...i, itemType: 'insight' as const })),
        ...recentDashboards.map((d) => ({ ...d, itemType: 'dashboard' as const })),
    ]
        .sort((a, b) => new Date(b.last_viewed_at || 0).getTime() - new Date(a.last_viewed_at || 0).getTime())
        .slice(0, 5)

    return (
        <CompactList
            title="Recently viewed"
            viewAllURL={urls.savedInsights(SavedInsightsTabs.All)}
            viewAllDataAttr="insights-home-tab-recently-viewed-view-all"
            loading={recentInsightsLoading}
            emptyMessage={{
                title: 'You have no recently viewed insights',
                description: "Explore this project's insights by clicking below.",
                buttonText: 'View insights',
                buttonTo: urls.savedInsights(),
            }}
            items={items}
            renderRow={(item: RecentItem) => {
                if (item.itemType === 'insight') {
                    return (
                        <InsightRow
                            key={item.short_id}
                            insight={item}
                            isExpanded={expandedInsightIds.has(item.short_id)}
                            onToggle={() => toggleInsightExpanded(item.short_id)}
                            dataAttr="recently-viewed-insight-item"
                        />
                    )
                }

                return (
                    <div
                        key={item.id}
                        className="border border-border rounded bg-surface-primary mb-2 last:mb-0"
                        data-attr="recently-viewed-dashboard-item"
                    >
                        <div className="flex items-center gap-3 p-3 rounded-t">
                            <IconDashboard className="text-secondary text-3xl shrink-0" />
                            <div className="flex flex-col flex-1 truncate">
                                <span className="font-semibold truncate">{item.name || <i>Untitled</i>}</span>
                                <span className="text-muted text-xs mt-0.5 truncate">
                                    {`Last viewed ${dayjs(item.last_viewed_at).fromNow()}`}
                                </span>
                            </div>
                            <LemonButton
                                size="small"
                                icon={<IconExternal />}
                                to={urls.dashboard(item.id)}
                                tooltip="Open dashboard"
                            />
                        </div>
                    </div>
                )
            }}
            contentHeightBehavior="fit-content"
        />
    )
}
