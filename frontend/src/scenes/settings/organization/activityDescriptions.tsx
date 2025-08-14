import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToOrganization = (name?: string | null): string | JSX.Element => {
    let displayName = name || 'Organization'

    if (displayName.length > 32) {
        displayName = displayName.slice(0, 32) + '...'
    }

    return <Link to={urls.settings('organization')}>{displayName}</Link>
}

export function organizationActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the organization{' '}
                    <strong>{nameOrLinkToOrganization(logItem?.detail.name)}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the organization{' '}
                    <strong>{logItem.detail.name || 'Organization'}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes = logItem.detail.changes || []

        if (changes.length === 1) {
            const change = changes[0]
            const changeDescription = `updated the ${change.field}`

            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> {changeDescription} for{' '}
                        {nameOrLinkToOrganization(logItem?.detail.name)}
                    </>
                ),
            }
        } else if (changes.length > 1) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> updated {changes.length} settings for{' '}
                        {nameOrLinkToOrganization(logItem?.detail.name)}
                    </>
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, nameOrLinkToOrganization(logItem?.detail.name))
}
