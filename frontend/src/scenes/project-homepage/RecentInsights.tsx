import React from 'react'
import './ProjectHomepage.scss'
import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { LemonButton } from 'lib/components/LemonButton'
import { urls } from 'scenes/urls'
import { InsightModel } from '~/types'

import { InsightIcon } from 'scenes/saved-insights/SavedInsights'
import { projectHomepageLogic } from './projectHomepageLogic'

interface InsightRowProps {
    insight: InsightModel
}

function InsightRow({ insight }: InsightRowProps): JSX.Element {
    return (
        <LemonButton fullWidth className="list-row" to={urls.insightView(insight.short_id)}>
            <InsightIcon insight={insight} />
            <div className="row-text-container" style={{ flexDirection: 'column', display: 'flex' }}>
                <p className="row-title link-text">{insight.name || insight.derived_name}</p>
                <p>Last modified {dayjs(insight.last_modified_at).fromNow()}</p>
            </div>
        </LemonButton>
    )
}

export function RecentInsights(): JSX.Element {
    const { recentInsights, recentInsightsLoading } = useValues(projectHomepageLogic)

    return (
        <>
            <CompactList
                title="Your recently viewed insights"
                viewAllURL={urls.savedInsights()}
                loading={recentInsightsLoading}
                emptyMessage={{
                    title: 'You have no recently viewed insights',
                    description: 'To start exploring insights, take a look at your projects saved insights.',
                    buttonText: 'Saved insights',
                    buttonTo: urls.savedInsights(),
                }}
                items={recentInsights.slice(0, 5)}
                renderRow={(insight: InsightModel, index) => <InsightRow key={index} insight={insight} />}
            />
        </>
    )
}
