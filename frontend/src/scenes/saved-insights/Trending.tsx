import { useActions, useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'
import { InsightIcon } from './SavedInsights'
import { trendingInsightsLogic } from './trendingInsightsLogic'

interface InsightRowProps {
    insight: QueryBasedInsightModel
}

function InsightRow({ insight }: InsightRowProps): JSX.Element {
    const { reportInsightOpenedFromRecentInsightList } = useActions(eventUsageLogic)

    return (
        <ProjectHomePageCompactListItem
            title={insight.name || insight.derived_name || 'Insight'}
            subtitle={`Last modified ${dayjs(insight.last_modified_at).fromNow()}`}
            prefix={<InsightIcon insight={insight} />}
            to={urls.insightView(insight.short_id)}
            onClick={() => {
                reportInsightOpenedFromRecentInsightList()
            }}
        />
    )
}

export function Trending(): JSX.Element {
    const { trendingInsights, trendingInsightsLoading } = useValues(trendingInsightsLogic)

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
            renderRow={(insight: QueryBasedInsightModel, index) => <InsightRow key={index} insight={insight} />}
        />
    )
}
