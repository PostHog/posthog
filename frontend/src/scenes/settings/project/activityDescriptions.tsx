import {
    ActivityLogItem,
    Describer,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

const projectNameForLog = (logItem: ActivityLogItem): string => {
    const context = logItem.detail?.context
    return context?.project_name || context?.organization_name || 'this project'
}

const keyLabel = (logItem: ActivityLogItem): string => {
    return logItem.detail?.name || 'Unknown key'
}

export const projectSecretAPIKeyActivityDescriber: Describer = (logItem: ActivityLogItem): HumanizedChange => {
    if (logItem.scope !== 'ProjectSecretAPIKey') {
        console.error('projectSecretAPIKeyActivityDescriber received a non-ProjectSecretAPIKey activity')
        return { description: null }
    }

    const actor = <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
    const keyName = <strong>{keyLabel(logItem)}</strong>
    const scopeName = <strong>{projectNameForLog(logItem)}</strong>

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    {actor} created project secret API key {keyName} for {scopeName}
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        const rolled = logItem.detail?.changes?.some((change) => change.field === 'mask_value')

        if (rolled) {
            return {
                description: (
                    <>
                        {actor} rolled project secret API key {keyName} for {scopeName}
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    {actor} updated project secret API key {keyName} for {scopeName}
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    {actor} deleted project secret API key {keyName} for {scopeName}
                </>
            ),
        }
    }

    return defaultDescriber(logItem)
}
