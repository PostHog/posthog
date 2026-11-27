import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'

export function userActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'User') {
        console.error('user describer received a non-user activity')
        return { description: null }
    }

    const context = logItem?.detail?.context as any

    if (logItem.activity === 'logged_in') {
        const loginMethod = context?.login_method || 'an unknown method'
        const reauthSensitiveOps = context?.reauth

        return {
            summary: activityLogSummary(
                logItem,
                reauthSensitiveOps ? 'Re-authenticated for sensitive operations' : 'Logged in',
                'Account',
                `Using ${loginMethod}`
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> logged in using {loginMethod}
                    {reauthSensitiveOps && <> (re-authenticated for sensitive operations)</>}
                </>
            ),
        }
    }

    if (logItem.activity === 'session_refused_unbound') {
        return {
            summary: activityLogSummary(logItem, 'Session ended', 'Account', 'Used without its device'),
            description: (
                <>
                    PostHog ended a session for <ActivityLogUserName logItem={logItem} /> because it was used without
                    the device it was signed in on
                </>
            ),
        }
    }

    if (logItem.activity === 'logged_out') {
        return {
            summary: activityLogSummary(logItem, 'Logged out', 'Account'),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> logged out
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification)
}
