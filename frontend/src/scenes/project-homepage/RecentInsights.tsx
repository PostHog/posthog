import './ProjectHomepage.scss'

import { useActions, useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useEffect } from 'react'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'
import { urls } from 'scenes/urls'

import { InsightModel } from '~/types'

import { ProjectHomePageCompactListItem } from './ProjectHomePageCompactListItem'
import { projectHomepageLogic } from './projectHomepageLogic'

interface InsightRowProps {
    insight: InsightModel
}

export function InsightRow({ insight }: InsightRowProps): JSX.Element {
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

export function RecentInsights(): JSX.Element {
    const { recentInsights, recentInsightsLoading } = useValues(projectHomepageLogic)
    const { loadRecentInsights } = useActions(projectHomepageLogic)

    useEffect(() => {
        loadRecentInsights()
    }, [])
    return (
        <>
            <CompactList
                title="Your recently viewed insights"
                viewAllURL={urls.savedInsights()}
                loading={recentInsightsLoading}
                emptyMessage={{
                    title: 'You have no recently viewed insights',
                    description: "Explore this project's insights by clicking below.",
                    buttonText: 'View insights',
                    buttonTo: urls.savedInsights(),
                }}
                items={recentInsights.slice(0, 5)}
                renderRow={(insight: InsightModel, index) => <InsightRow key={index} insight={insight} />}
            />
        </>
    )
}
