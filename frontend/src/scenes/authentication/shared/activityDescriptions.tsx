import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
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
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> logged in using {loginMethod}
                    {reauthSensitiveOps && <> (re-authenticated for sensitive operations)</>}
                </>
            ),
        }
    }

    if (logItem.activity === 'logged_out') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> logged out
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification)
}
