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
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created personal API key{' '}
                    <strong>{getKeyTitle()}</strong> for <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'revoked') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> revoked access for personal
                    API key <strong>{getKeyTitle()}</strong> to <strong>{getScopeDescription()}</strong>
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
                        <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> rolled personal API key{' '}
                        <strong>{getKeyTitle()}</strong> for <strong>{getScopeDescription()}</strong>
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated personal API key{' '}
                    <strong>{getKeyTitle()}</strong> for <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted personal API key{' '}
                    <strong>{getKeyTitle()}</strong> for access to <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem)
}

function asScopeList(value: unknown): string[] {
    return Array.isArray(value) ? value.map(String) : []
}

function ScopeList({ scopes }: { scopes: string[] }): JSX.Element {
    return (
        <>
            {scopes.map((scope, index) => (
                <span key={scope}>
                    {index > 0 && ', '}
                    <code>{scope}</code>
                </span>
            ))}
        </>
    )
}

export const oauthApplicationActivityDescriber: Describer = (logItem: ActivityLogItem): HumanizedChange => {
    if (logItem.scope !== 'OAuthApplication') {
        console.error('oauthApplicationActivityDescriber received a non-OAuthApplication activity')
        return { description: null }
    }

    const appName = logItem.detail.name || 'an OAuth application'
    const scopesChange = logItem.detail.changes?.find((change) => change.field === 'scopes')
    if (!scopesChange) {
        return defaultDescriber(logItem)
    }

    const actor = <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
    const before = asScopeList(scopesChange.before)
    const after = asScopeList(scopesChange.after)

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    {actor} registered OAuth application <strong>{appName}</strong> with scope ceiling{' '}
                    <ScopeList scopes={after} />
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        if (after.length === 0 && before.length > 0) {
            return {
                description: (
                    <>
                        {actor} removed the scope ceiling on <strong>{appName}</strong> (was{' '}
                        <ScopeList scopes={before} />; default unprivileged scopes now apply)
                    </>
                ),
            }
        }

        if (before.length === 0 && after.length > 0) {
            return {
                description: (
                    <>
                        {actor} set the scope ceiling on <strong>{appName}</strong> to <ScopeList scopes={after} />
                    </>
                ),
            }
        }

        const added = after.filter((scope) => !before.includes(scope))
        const removed = before.filter((scope) => !after.includes(scope))

        if (added.length > 0 && removed.length > 0) {
            return {
                description: (
                    <>
                        {actor} changed the scope ceiling on <strong>{appName}</strong>: added{' '}
                        <ScopeList scopes={added} />, removed <ScopeList scopes={removed} />
                    </>
                ),
            }
        }
        if (added.length > 0) {
            return {
                description: (
                    <>
                        {actor} widened the scope ceiling on <strong>{appName}</strong>: added{' '}
                        <ScopeList scopes={added} />
                    </>
                ),
            }
        }
        if (removed.length > 0) {
            return {
                description: (
                    <>
                        {actor} narrowed the scope ceiling on <strong>{appName}</strong>: removed{' '}
                        <ScopeList scopes={removed} />
                    </>
                ),
            }
        }

        return defaultDescriber(logItem)
    }

    return defaultDescriber(logItem)
}
