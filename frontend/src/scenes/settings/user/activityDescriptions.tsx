import {
    ActivityLogItem,
    ActivityLogUserName,
    Describer,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
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
            summary: activityLogSummary(
                logItem,
                'Created the personal API key',
                <>
                    {getKeyTitle()} · {getScopeDescription()}
                </>
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created personal API key <strong>{getKeyTitle()}</strong>{' '}
                    for <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'revoked') {
        return {
            summary: activityLogSummary(
                logItem,
                'Revoked the personal API key',
                <>
                    {getKeyTitle()} · {getScopeDescription()}
                </>
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> revoked access for personal API key{' '}
                    <strong>{getKeyTitle()}</strong> to <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        const rolledChangeDescription = logItem.detail.changes?.find((change) => change.field === 'mask_value')

        if (rolledChangeDescription) {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Rolled the personal API key',
                    <>
                        {getKeyTitle()} · {getScopeDescription()}
                    </>
                ),
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> rolled personal API key{' '}
                        <strong>{getKeyTitle()}</strong> for <strong>{getScopeDescription()}</strong>
                    </>
                ),
            }
        }

        return {
            summary: activityLogSummary(
                logItem,
                'Updated the personal API key',
                <>
                    {getKeyTitle()} · {getScopeDescription()}
                </>
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> updated personal API key <strong>{getKeyTitle()}</strong>{' '}
                    for <strong>{getScopeDescription()}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            summary: activityLogSummary(
                logItem,
                'Deleted the personal API key',
                <>
                    {getKeyTitle()} · {getScopeDescription()}
                </>
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted personal API key <strong>{getKeyTitle()}</strong>{' '}
                    for access to <strong>{getScopeDescription()}</strong>
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

    const actor = <ActivityLogUserName logItem={logItem} />
    const before = asScopeList(scopesChange.before)
    const after = asScopeList(scopesChange.after)

    if (logItem.activity === 'created') {
        return {
            summary: activityLogSummary(
                logItem,
                'Registered the OAuth application',
                appName,
                `Scope ceiling: ${after.join(', ')}`
            ),
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
                summary: activityLogSummary(
                    logItem,
                    'Removed the scope ceiling',
                    appName,
                    `Previously ${before.join(', ')}. Default unprivileged scopes now apply.`
                ),
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
                summary: activityLogSummary(logItem, 'Set the scope ceiling', appName, after.join(', ')),
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
                summary: activityLogSummary(
                    logItem,
                    'Changed the scope ceiling',
                    appName,
                    `Added ${added.join(', ')}; removed ${removed.join(', ')}`
                ),
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
                summary: activityLogSummary(logItem, 'Widened the scope ceiling', appName, `Added ${added.join(', ')}`),
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
                summary: activityLogSummary(
                    logItem,
                    'Narrowed the scope ceiling',
                    appName,
                    `Removed ${removed.join(', ')}`
                ),
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
