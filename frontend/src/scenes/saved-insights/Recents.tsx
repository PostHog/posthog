import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconExternal } from '@posthog/icons'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { projectHomepageLogic } from '../project-homepage/projectHomepageLogic'
import { InsightIcon } from './SavedInsights'

interface InsightRowProps {
    insight: QueryBasedInsightModel
}

function InsightRow({ insight }: InsightRowProps): JSX.Element {
    const { reportInsightOpenedFromRecentInsightList } = useActions(eventUsageLogic)
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <div className="border border-border rounded bg-surface-primary mb-2 last:mb-0">
            <div
                className="flex items-center gap-3 p-3 cursor-pointer hover:bg-surface-secondary rounded-t"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className={`transform transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                    <IconChevronRight className="text-xl" />
                </div>
                <InsightIcon insight={insight} className="text-secondary text-3xl" />
                <div className="flex flex-col flex-1 truncate">
                    <span className="font-semibold truncate">{insight.name || insight.derived_name || 'Insight'}</span>
                    <span className="text-muted text-xs mt-0.5 truncate">
                        {`Last modified ${dayjs(insight.last_modified_at).fromNow()}`}
                    </span>
                </div>
            </div>
            {isExpanded && (
                <div className="border-t border-border bg-surface-primary">
                    <div className="p-4 h-60 relative">
                        <Query
                            query={insight.query}
                            readOnly
                            embedded
                            context={{ insightProps: { dashboardItemId: insight.short_id as any } }}
                        />
                    </div>
                    <div className="flex justify-end items-center p-3 border-t border-border">
                        <LemonButton
                            type="primary"
                            icon={<IconExternal />}
                            to={urls.insightView(insight.short_id)}
                            onClick={() => reportInsightOpenedFromRecentInsightList()}
                        >
                            Open insight
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
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
            contentHeightBehavior="fit-content"
        />
    )
}
