import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

interface PlatformAlertActivityContext {
    source_kind?: string
    source_id?: InsightShortId | null
    source_name?: string | null
}

const SUMMARY_ACTIONS: Record<string, string> = { created: 'Created', updated: 'Updated', deleted: 'Deleted' }

function alertName(logItem: ActivityLogItem): JSX.Element {
    const name = logItem.detail?.name || 'Alert'
    const context = logItem.detail?.context as PlatformAlertActivityContext | undefined
    // A deleted logs alert has no page left to open.
    if (context?.source_kind === 'logs' && logItem.activity !== 'deleted' && logItem.item_id) {
        return <Link to={urls.logsAlertDetail(logItem.item_id)}>{name}</Link>
    }
    return <strong>{name}</strong>
}

function watched(logItem: ActivityLogItem): JSX.Element | null {
    const context = logItem.detail?.context as PlatformAlertActivityContext | undefined
    if (context?.source_kind !== 'insight' || !context.source_id) {
        return null
    }
    return (
        <>
            {' '}
            on insight <Link to={urls.insightView(context.source_id)}>{context.source_name || context.source_id}</Link>
        </>
    )
}

export function platformAlertConfigurationActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    const action = SUMMARY_ACTIONS[logItem.activity]
    if (!action) {
        return defaultDescriber(logItem, asNotification, alertName(logItem))
    }
    const kind = (logItem.detail?.context as PlatformAlertActivityContext | undefined)?.source_kind
    const noun = kind === 'logs' ? 'logs alert' : 'alert'
    return {
        summary: activityLogSummary(
            logItem,
            `${action} the ${noun}`,
            <>
                {alertName(logItem)}
                {watched(logItem)}
            </>
        ),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> {logItem.activity} the {noun} {alertName(logItem)}
                {watched(logItem)}
            </>
        ),
    }
}
