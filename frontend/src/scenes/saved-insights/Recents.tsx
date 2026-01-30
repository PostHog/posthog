import { useActions, useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'
import { projectHomepageLogic } from '../project-homepage/projectHomepageLogic'
import { InsightIcon } from './SavedInsights'

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

export function Recents(): JSX.Element {
    const { recentInsights, recentInsightsLoading } = useValues(projectHomepageLogic)
    const { loadRecentInsights } = useActions(projectHomepageLogic)
    useOnMountEffect(loadRecentInsights)

    return (
        <CompactList
            title="Recents"
            viewAllURL={urls.savedInsights(SavedInsightsTabs.All)}
            loading={recentInsightsLoading}
            emptyMessage={{
                title: 'You have no recently viewed insights',
                description: "Explore this project's insights by clicking below.",
                buttonText: 'View insights',
                buttonTo: urls.savedInsights(),
            }}
            items={recentInsights.slice(0, 5)}
            renderRow={(insight: QueryBasedInsightModel, index) => <InsightRow key={index} insight={insight} />}
        />
    )
}
