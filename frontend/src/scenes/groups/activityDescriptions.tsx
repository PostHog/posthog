import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

export function groupActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Group') {
        console.error('group describer received a non-group activity')
        return { description: null }
    }

    if (logItem.activity === 'update_property') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> edited the <code>{logItem.detail.name}</code>{' '}
                    property.
                </>
            ),
        }
    }

    if (logItem.activity === 'delete_property') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the <code>{logItem.detail.name}</code>{' '}
                    property.
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification)
}
