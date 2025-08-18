import '../../lib/components/Cards/InsightCard/InsightCard.scss'

import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToCohort = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.cohort(id)}>{displayName}</Link> : displayName
}

export function cohortActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Cohort') {
        console.error('cohort describer received a non-cohort activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the cohort:{' '}
                    {nameOrLinkToCohort(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the cohort: {logItem.detail.name}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated the cohort:{' '}
                    {nameOrLinkToCohort(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToCohort(logItem?.detail.short_id))
}
