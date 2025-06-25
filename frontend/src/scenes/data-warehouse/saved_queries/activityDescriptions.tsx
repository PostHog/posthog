import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

export function dataWarehouseSavedQueryActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    if (logItem.scope !== 'DataWarehouseSavedQuery') {
        console.error('data warehouse saved query describer received a non-data warehouse saved query activity')
        return { description: null }
    }

    if (logItem.activity === 'created') {
        return {
            description: (
                <SentenceList
                    listParts={[<>created a new view</>]}
                    prefix={
                        <>
                            <strong>{userNameForLogItem(logItem)}</strong>
                        </>
                    }
                />
            ),
        }
    }

    if (logItem.activity === 'updated') {
        return {
            description: (
                <SentenceList
                    listParts={[<>updated the view</>]}
                    prefix={
                        <>
                            <strong>{userNameForLogItem(logItem)}</strong>
                        </>
                    }
                />
            ),
        }
    }

    return defaultDescriber(logItem, asNotification)
}
