import { useValues } from 'kea'

import { ActivityLogLogicProps, activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLogRow'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { urls } from 'scenes/urls'

import { ActivityScope, SavedInsightsTabs } from '~/types'

const ACTIVITY_LIMIT = 5

export function Activity(): JSX.Element {
    const logic = activityLogLogic({ scope: ActivityScope.INSIGHT } satisfies ActivityLogLogicProps)
    const { humanizedActivity, activityLoading } = useValues(logic)

    return (
        <CompactList
            title="Activity"
            viewAllURL={urls.savedInsights(SavedInsightsTabs.History)}
            viewAllDataAttr="insights-home-tab-activity-view-all"
            loading={activityLoading}
            emptyMessage={{
                title: 'No activity yet',
                description: 'Activity on insights will appear here.',
                buttonText: 'View all activity',
                buttonTo: urls.savedInsights(SavedInsightsTabs.History),
            }}
            items={humanizedActivity.slice(0, ACTIVITY_LIMIT)}
            renderRow={(logItem: HumanizedActivityLogItem, index) => (
                <div key={index} className="mb-2 last:mb-0" data-attr="activity-log-item">
                    <ActivityLogRow logItem={logItem} />
                </div>
            )}
            contentHeightBehavior="fit-content"
        />
    )
}
