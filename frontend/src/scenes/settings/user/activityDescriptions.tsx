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

    if (logItem.activity === 'revoked') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> revoked access for personal API key{' '}
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
