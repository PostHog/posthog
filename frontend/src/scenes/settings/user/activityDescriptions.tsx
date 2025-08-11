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

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created personal API key{' '}
                    <strong>{logItem.detail.name}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        const nameChangeDescription = logItem.detail.changes?.find((change) => change.field === 'label')

        if (nameChangeDescription) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> renamed personal API key from{' '}
                        <strong>{nameChangeDescription.before}</strong> to{' '}
                        <strong>{nameChangeDescription.after}</strong>
                    </>
                ),
            }
        }

        const scopeChangeDescription = logItem.detail.changes?.find((change) => change.field === 'scopes')

        if (scopeChangeDescription) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> updated scopes for personal API key{' '}
                        <strong>{logItem.detail.name}</strong>
                    </>
                ),
            }
        }

        const scopedTeamsChangeDescription = logItem.detail.changes?.find((change) => change.field === 'scoped_teams')

        if (scopedTeamsChangeDescription) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> updated team scope for personal API key{' '}
                        <strong>{logItem.detail.name}</strong>
                    </>
                ),
            }
        }

        const scopedOrgsChangeDescription = logItem.detail.changes?.find(
            (change) => change.field === 'scoped_organizations'
        )

        if (scopedOrgsChangeDescription) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> updated organization scope for personal API key{' '}
                        <strong>{logItem.detail.name}</strong>
                    </>
                ),
            }
        }

        const rolledChangeDescription = logItem.detail.changes?.find((change) => change.field === 'last_rolled_at')

        if (rolledChangeDescription) {
            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> rolled personal API key{' '}
                        <strong>{logItem.detail.name}</strong>
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated personal API key{' '}
                    <strong>{logItem.detail.name}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted personal API key{' '}
                    <strong>{logItem.detail.name}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem)
}
