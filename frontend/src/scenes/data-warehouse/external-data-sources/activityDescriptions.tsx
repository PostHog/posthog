import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope, DataWarehouseSyncInterval, ExternalDataSourceSyncSchema } from '~/types'

import { SyncTypeLabelMap } from '../utils'

const getSyncFrequencyLabel = (syncFrequency: string): string => {
    const syncFrequencyMap: Record<DataWarehouseSyncInterval, string> = {
        '5min': 'every 5 mins',
        '30min': 'every 30 mins',
        '1hour': 'every 1 hour',
        '6hour': 'every 6 hours',
        '12hour': 'every 12 hours',
        '24hour': 'daily',
        '7day': 'weekly',
        '30day': 'monthly',
    }
    return syncFrequencyMap[syncFrequency as DataWarehouseSyncInterval] || syncFrequency
}

const getDisplayName = (logItem: ActivityLogItem): string => {
    const name = logItem?.detail?.name
    if (name) {
        return name
    }

    // Handle ExternalDataSource display name
    if (logItem.scope === ActivityScope.EXTERNAL_DATA_SOURCE) {
        const sourceType = (logItem?.detail as any)?.source_type
        const prefix = (logItem?.detail as any)?.prefix

        if (sourceType && prefix) {
            return `${sourceType} (${prefix})`
        } else if (sourceType) {
            return sourceType
        }
    }

    // Handle ExternalDataSchema display name
    if (logItem.scope === ActivityScope.EXTERNAL_DATA_SCHEMA) {
        const schemaName = logItem?.detail?.name || 'Unnamed Schema'
        const context = (logItem?.detail as any)?.context
        const syncType = context?.sync_type
        const syncFrequency = context?.sync_frequency

        const humanizedSyncType = syncType
            ? SyncTypeLabelMap[syncType as NonNullable<ExternalDataSourceSyncSchema['sync_type']>] || syncType
            : null
        const humanizedSyncFrequency = syncFrequency ? getSyncFrequencyLabel(syncFrequency) : null

        if (humanizedSyncType && humanizedSyncFrequency) {
            return `${schemaName} (${humanizedSyncType}, ${humanizedSyncFrequency})`
        } else if (humanizedSyncType) {
            return `${schemaName} (${humanizedSyncType})`
        }
        return schemaName
    }

    return 'Source'
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
                        <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created schema{' '}
                        <strong>{displayName}</strong>
                    </>
                ),
            }
        }
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created source{' '}
                    <strong>{displayName}</strong>
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
                        <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted schema{' '}
                        <strong>{displayName}</strong>
                    </>
                ),
            }
        }
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted source{' '}
                    <strong>{displayName}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        if (logItem.scope === ActivityScope.EXTERNAL_DATA_SCHEMA) {
            return {
                description: (
                    <>
                        <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated schema{' '}
                        <strong>{displayName}</strong>
                    </>
                ),
            }
        }
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated source{' '}
                    <strong>{displayName}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, displayName)
}
