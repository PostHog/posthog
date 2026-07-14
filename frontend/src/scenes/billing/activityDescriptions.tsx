import {
    ActivityChange,
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

// The billing service sets detail.name; map it to a short verb phrase for the feed.
const BILLING_ACTIONS: Record<string, string> = {
    'Billing spend limits': 'updated the spend limits',
    'Billing next-period limit reset': 'reset a next-period spend limit',
    'Billing products activated': 'added products',
    'Billing products deactivated': 'removed products',
    'Billing plan switched': 'switched plan',
    'Billing trial activated': 'started a trial',
    'Billing trial extended': 'extended a trial',
    'Billing trial cancelled': 'cancelled a trial',
    'Billing credits purchased': 'purchased credits',
}

const formatValue = (value: ActivityChange['before']): string =>
    value === null || value === undefined ? 'none' : `${value}`

const describeChanges = (changes: ActivityChange[]): string | null => {
    if (changes.length === 1 && changes[0].action === 'changed' && changes[0].field) {
        const change = changes[0]
        return `${change.field} from ${formatValue(change.before)} to ${formatValue(change.after)}`
    }
    const fields = changes.map((change) => change.field).filter((field): field is string => !!field)
    return fields.length ? fields.join(', ') : null
}

export function billingActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    // Every billing_activity row is written as an "updated" activity; fall back for anything else.
    if (logItem.activity !== 'updated') {
        return defaultDescriber(logItem, asNotification)
    }

    const action = BILLING_ACTIONS[logItem.detail.name || ''] || 'updated billing'
    const detail = describeChanges(logItem.detail.changes || [])

    return {
        description: (
            <>
                <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> {action} in{' '}
                <Link to={urls.organizationBilling()}>billing</Link>
                {detail ? ` (${detail})` : ''}
            </>
        ),
    }
}
