import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToBatchExport = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(unnamed export)'
    return id ? <Link to={urls.batchExport(id)}>{displayName}</Link> : `${displayName}`
}

export function batchExportActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong> {userNameForLogItem(logItem)}</strong> created destination{' '}
                    <strong>{nameOrLinkToBatchExport(logItem?.item_id, logItem?.detail.name)}</strong>
                </>
            ),
        }
    }

    if (logItem.detail?.changes?.some((change) => change.field === 'deleted')) {
        const displayName = logItem.detail.name || '(unnamed export)'
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted destination <strong>{displayName}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated destination{' '}
                    <strong>{nameOrLinkToBatchExport(logItem?.item_id, logItem?.detail.name)}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, nameOrLinkToBatchExport(logItem?.item_id, logItem?.detail.name))
}
