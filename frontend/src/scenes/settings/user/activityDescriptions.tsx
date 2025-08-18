import {
    ActivityLogItem,
    defaultDescriber,
    Describer,
    HumanizedChange,
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

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created a <strong>personal API key</strong> for{' '}
                    <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'revoked') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> revoked access for <strong>personal API key</strong>{' '}
                    to <strong>{getScopeDescription()}</strong>
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
                        <strong>{userNameForLogItem(logItem)}</strong> rolled <strong>personal API key</strong> for{' '}
                        <strong>{getScopeDescription()}</strong>
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated <strong>personal API key</strong> for{' '}
                    <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted <strong>personal API key</strong> for access
                    to <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem)
}
