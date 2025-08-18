import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ActivityScope } from '~/types'

const getDisplayName = (logItem: ActivityLogItem): string => {
    const name = logItem?.detail?.name
    if (name) {
        return name
    }

    // Handle ExternalDataSource display name
    if (logItem.scope === ActivityScope.EXTERNAL_DATA_SOURCE) {
        const sourceType = logItem?.detail?.source_type
        const prefix = logItem?.detail?.prefix

        if (sourceType && prefix) {
            return `${sourceType} (${prefix})`
        } else if (sourceType) {
            return sourceType
        }
    }

    // Handle ExternalDataSchema display name
    if (logItem.scope === ActivityScope.EXTERNAL_DATA_SCHEMA) {
        const schemaName = logItem?.detail?.name || 'Unnamed Schema'
        const syncType = logItem?.detail?.sync_type
        const syncFrequency = logItem?.detail?.sync_frequency

        if (syncType && syncFrequency) {
            return `${schemaName} (${syncType}, ${syncFrequency})`
        } else if (syncType) {
            return `${schemaName} (${syncType})`
        }
        return schemaName
    }

    return 'External Data Source'
}

export function externalDataSourceActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    const displayName = getDisplayName(logItem)

    if (logItem.activity == 'created') {
        if (logItem.scope === ActivityScope.EXTERNAL_DATA_SCHEMA) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> created schema <strong>{displayName}</strong>
                    </>
                ),
            }
        }
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created source <strong>{displayName}</strong>
                </>
            ),
        }
    }

    if (
        logItem.activity == 'deleted' ||
        (logItem.activity == 'updated' &&
            logItem.detail?.changes?.some((change: any) => change.field === 'deleted' && change.after === true))
    ) {
        if (logItem.scope === ActivityScope.EXTERNAL_DATA_SCHEMA) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> deleted schema <strong>{displayName}</strong>
                    </>
                ),
            }
        }
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted source <strong>{displayName}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        if (logItem.scope === ActivityScope.EXTERNAL_DATA_SCHEMA) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> updated schema <strong>{displayName}</strong>
                    </>
                ),
            }
        }
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated source <strong>{displayName}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, displayName)
}
