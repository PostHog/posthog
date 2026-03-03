import { useValues } from 'kea'

import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityLogLogicProps, activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { urls } from 'scenes/urls'

import { ActivityScope, SavedInsightsTabs } from '~/types'

const ACTIVITY_LIMIT = 5

export function Activity(): JSX.Element {
    const logicProps: ActivityLogLogicProps = {
        scope: ActivityScope.INSIGHT,
    }
    const logic = activityLogLogic(logicProps)
    const { humanizedActivity, activityLoading } = useValues(logic)

    return (
        <CompactList
            title="Activity"
            viewAllURL={urls.savedInsights(SavedInsightsTabs.History)}
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
