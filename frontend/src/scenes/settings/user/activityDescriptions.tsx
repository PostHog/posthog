import {
    ActivityLogItem,
    Describer,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

export const personalAPIKeyActivityDescriber: Describer = (logItem: ActivityLogItem): HumanizedChange => {
    if (logItem.scope !== 'PersonalAPIKey') {
        console.error('personalAPIKeyActivityDescriber received a non-PersonalAPIKey activity')
        return { description: null }
    }

    const getScopeDescription = (): string => {
        const context = logItem.detail.context
        if (context?.team_name && context.team_name !== 'Unknown Project') {
            return context.team_name
        }
        if (context?.organization_name) {
            return context.organization_name
        }
        return 'Unknown scope'
    }

    const getKeyTitle = (): string => {
        return logItem.detail.name || 'Unknown key'
    }

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created personal API key{' '}
                    <strong>{getKeyTitle()}</strong> for <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'revoked') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> revoked access for personal API key{' '}
                    <strong>{getKeyTitle()}</strong> to <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        const rolledChangeDescription = logItem.detail.changes?.find((change) => change.field === 'mask_value')

        if (rolledChangeDescription) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> rolled personal API key{' '}
                        <strong>{getKeyTitle()}</strong> for <strong>{getScopeDescription()}</strong>
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated personal API key{' '}
                    <strong>{getKeyTitle()}</strong> for <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted personal API key{' '}
                    <strong>{getKeyTitle()}</strong> for access to <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem)
}
