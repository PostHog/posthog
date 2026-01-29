import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToTour = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.productTour(id)}>{displayName}</Link> : displayName
}

export function productTourActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'ProductTour') {
        console.error('product tour describer received a non-product tour activity')
        return { description: null }
    }

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created the product tour:{' '}
                    {nameOrLinkToTour(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated the product tour:{' '}
                    {nameOrLinkToTour(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted the product tour:{' '}
                    {nameOrLinkToTour(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, nameOrLinkToTour(logItem?.item_id, logItem?.detail.name))
}
