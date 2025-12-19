import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

const getDisplayName = (logItem: ActivityLogItem): string => {
    const name = logItem?.detail?.name
    if (name) {
        return name
    }

    const context = logItem?.detail?.context as any
    if (context?.source_type && context?.content_type) {
        return `source ${context.source_type} (${context.content_type})`
    }

    const detail = logItem?.detail as any
    const config = detail?.import_config
    if (config?.source?.type) {
        return `source ${config.source.type}`
    }

    return 'unknown source'
}

export function batchImportActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created{' '}
                    <strong>{getDisplayName(logItem)}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted{' '}
                    <strong>{getDisplayName(logItem)}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated{' '}
                    <strong>{getDisplayName(logItem)}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, getDisplayName(logItem))
}
