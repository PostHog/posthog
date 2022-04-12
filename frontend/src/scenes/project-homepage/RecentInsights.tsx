import React from 'react'
import './RecentInsights.scss'
import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'

import './RecentRecordings.scss'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { LemonButton } from 'lib/components/LemonButton'
import { urls } from 'scenes/urls'
import { InsightModel } from '~/types'

import { recentInsightsLogic } from './recentInsightsLogic'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'

interface InsightRowProps {
    insight: InsightModel
}

function InsightRow({ insight }: InsightRowProps): JSX.Element {
    return (
        <LemonButton fullWidth className="insight-row" to={urls.insightView(insight.short_id)}>
            <InsightIcon insight={insight} />

            <div className="insight-text-container" style={{ flexDirection: 'column', display: 'flex' }}>
                <p className="insight-name">{insight.name}</p>
                <p className="insight-last-modified">Last modified {dayjs(insight.last_modified_at).fromNow()}</p>
            </div>
        </LemonButton>
    )
}

export function RecentInsights(): JSX.Element {
    const { recentInsights, recentInsightsLoading } = useValues(recentInsightsLogic)

    return (
        <>
            <CompactList
                title="Your recently viewed insights"
                viewAllURL={urls.savedInsights()}
                loading={recentInsightsLoading}
                emptyMessage={{
                    title: 'There are no recently viewed insights',
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
