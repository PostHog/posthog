import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToBatchExport = (
    id?: string | null,
    name?: string | null,
    destinationType?: string
): string | JSX.Element => {
    const displayName = name || '(unnamed export)'
    const suffix = destinationType ? ` to ${destinationType}` : ''
    return id ? (
        <Link to={urls.batchExport(id)}>
            {displayName}
            {suffix}
        </Link>
    ) : (
        `${displayName}${suffix}`
    )
}

export function batchExportActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const context = logItem?.detail?.context as any
    const destinationType = context?.destination_type

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created batch export{' '}
                    {nameOrLinkToBatchExport(logItem?.item_id, logItem?.detail.name, destinationType)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        const displayName = logItem.detail.name || '(unnamed export)'
        const suffix = destinationType ? ` to ${destinationType}` : ''
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted batch export "{displayName}
                    {suffix}"
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated batch export{' '}
                    {nameOrLinkToBatchExport(logItem?.item_id, logItem?.detail.name, destinationType)}
                </>
            ),
        }
    }

    return defaultDescriber(
        logItem,
        asNotification,
        nameOrLinkToBatchExport(logItem?.item_id, logItem?.detail.name, destinationType)
    )
}
