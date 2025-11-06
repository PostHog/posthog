import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

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
                            <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
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
                            <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
                        </>
                    }
                />
            ),
        }
    }

    return defaultDescriber(logItem, asNotification)
}
