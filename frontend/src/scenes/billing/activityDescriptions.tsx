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
    'Billing trial canceled': 'canceled a trial',
    // Alias kept so rows written before the billing service adopted American spelling still render.
    'Billing trial cancelled': 'canceled a trial',
    'Billing credits purchased': 'purchased credits',
}

const formatValue = (value: ActivityChange['before']): string =>
    value === null || value === undefined ? 'none' : `${value}`

const describeChange = (change: ActivityChange): string | null => {
    if (!change.field) {
        return null
    }
    switch (change.action) {
        case 'changed':
            return `${change.field} from ${formatValue(change.before)} to ${formatValue(change.after)}`
        case 'created':
            return `${change.field}: ${formatValue(change.after)}`
        case 'deleted':
            return `${change.field}: ${formatValue(change.before)}`
        default:
            return change.field
    }
}

const describeChanges = (changes: ActivityChange[]): string | null => {
    if (changes.length === 1) {
        return describeChange(changes[0])
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
