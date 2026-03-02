import { useActions } from 'kea'

import { IconChevronRight, IconExternal } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { QueryBasedInsightModel } from '~/types'

import { InsightIcon } from './SavedInsights'

interface InsightRowProps {
    insight: QueryBasedInsightModel
    isExpanded: boolean
    onToggle: () => void
    dataAttr?: string
}

export function InsightRow({ insight, isExpanded, onToggle, dataAttr }: InsightRowProps): JSX.Element {
    const { reportInsightOpenedFromRecentInsightList } = useActions(eventUsageLogic)

    return (
        <div className="border border-border rounded bg-surface-primary mb-2 last:mb-0" data-attr={dataAttr}>
            <div
                className="flex items-center gap-3 p-3 cursor-pointer hover:bg-surface-secondary rounded-t"
                onClick={onToggle}
            >
                <div className={`transform transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                    <IconChevronRight className="text-xl" />
                </div>
                <InsightIcon insight={insight} className="text-secondary text-3xl" />
                <div className="flex flex-col flex-1 truncate">
                    <span className="font-semibold truncate">
                        {insight.name || <i>{insight.derived_name || 'Insight'}</i>}
                    </span>
                    <span className="text-muted text-xs mt-0.5 truncate">
                        {`Last modified ${dayjs(insight.last_modified_at).fromNow()}`}
                    </span>
                </div>
                {insight.viewers && insight.viewers.length > 0 && (
                    <div className="flex items-center -space-x-2 mr-2">
                        {insight.viewers.slice(0, 3).map((viewer, index) => (
                            <ProfilePicture
                                key={viewer.uuid || index}
                                user={viewer}
                                size="md"
                                showName={false}
                                className="border-2 border-surface-primary"
                                title={`Viewed by ${viewer.first_name || viewer.email}`}
                            />
                        ))}
                        {insight.viewers.length > 3 && (
                            <div
                                className="w-6 h-6 rounded-full bg-surface-secondary border-2 border-surface-primary flex items-center justify-center text-xs font-semibold text-muted"
                                title={`${insight.viewers.length - 3} more viewers`}
                            >
                                +{insight.viewers.length - 3}
                            </div>
                        )}
                    </div>
                )}
                <LemonButton
                    size="small"
                    icon={<IconExternal />}
                    to={urls.insightView(insight.short_id)}
                    onClick={(e) => {
                        e.stopPropagation()
                        reportInsightOpenedFromRecentInsightList()
                    }}
                    tooltip="Open insight"
                />
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
