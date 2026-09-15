import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const formattedName = (name?: string | null): string | JSX.Element => {
    const displayName = name

    return <strong>{displayName}</strong>
}

const getContextDescription = (context: any): JSX.Element | null => {
    if (!context) {
        return null
    }

    if (context.insight_id && context.insight_short_id) {
        return (
            <>
                {' '}
                for insight{' '}
                <Link to={urls.insightView(context.insight_short_id)}>
                    {context.insight_name || context.insight_short_id}
                </Link>
            </>
        )
    }

    return null
}

export function alertConfigurationActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    if (logItem.scope != 'AlertConfiguration') {
        console.error('alert configuration describer received a non-alert-configuration activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
        const contextDesc = getContextDescription(logItem?.detail?.context)

        if (logItem.detail?.type === 'alert_subscription_change') {
            return {
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> added{' '}
                        <strong>
                            {logItem?.detail?.context?.subscriber_name} ({logItem?.detail?.context?.subscriber_email})
                        </strong>{' '}
                        as a subscriber for alert {formattedName(logItem?.detail?.context?.alert_name)}
                        {contextDesc}
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created the alert {formattedName(logItem?.detail.name)}
                    {contextDesc}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        const contextDesc = getContextDescription(logItem?.detail?.context)

        if (logItem.detail?.type === 'alert_subscription_change') {
            return {
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> removed{' '}
                        <strong>
                            {logItem?.detail?.context?.subscriber_name} ({logItem?.detail?.context?.subscriber_email})
                        </strong>{' '}
                        as a subscriber from alert {formattedName(logItem?.detail?.context?.alert_name)}
                        {contextDesc}
                    </>
                ),
            }
        }

        const displayName = logItem.detail.name || 'Alert Configuration'
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted the alert: {displayName}
                    {contextDesc}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const contextDesc = getContextDescription(logItem?.detail?.context)

        if (logItem.detail?.type === 'threshold_change') {
            return {
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> updated the <strong>threshold</strong> for alert{' '}
                        {formattedName(logItem?.detail?.context?.alert_name)}
                        {contextDesc}
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> updated the alert {formattedName(logItem?.detail.name)}
                    {contextDesc}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, formattedName(logItem?.detail.name))
}
