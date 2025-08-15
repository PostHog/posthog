import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

const getDisplayName = (logItem: ActivityLogItem): string => {
    const name = logItem?.detail?.name
    if (name) {
        return name
    }

    // Try to get info from the new context first
    const context = logItem?.detail?.context as any
    if (context?.source_type && context?.content_type) {
        return `${context.source_type} import (${context.content_type})`
    }

    // Fall back to the old method for backward compatibility
    const detail = logItem?.detail as any
    const config = detail?.import_config
    if (config?.source?.type) {
        return `${config.source.type} import`
    }

    return 'batch import'
}

export function batchImportActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created {getDisplayName(logItem)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted {getDisplayName(logItem)}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated {getDisplayName(logItem)}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, getDisplayName(logItem))
}
