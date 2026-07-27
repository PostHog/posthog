import { IconGear } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { IconBranch } from 'lib/lemon-ui/icons'

function manageInstallationUrl(installationId: string, accountType?: string, accountName?: string): string {
    return accountType === 'Organization' && accountName
        ? `https://github.com/organizations/${accountName}/settings/installations/${installationId}`
        : `https://github.com/settings/installations/${installationId}`
}

export function GitHubRepoSummary({
    repoNames,
    loading,
    installationId,
    accountType,
    accountName,
    onBeforeManage,
}: {
    repoNames: string[]
    loading: boolean
    installationId?: string | null
    accountType?: string
    accountName?: string
    /** Called before opening the GitHub installation settings page. Use this to seed
     * server-side state (via the `github_prepare_callback` endpoints) so the eventual
     * Setup URL callback can be dispatched to the right team/personal handler. */
    onBeforeManage?: (installationId: string) => Promise<void> | void
}): JSX.Element {
    const manageButton = installationId ? (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconGear />}
            onClick={async () => {
                try {
                    await onBeforeManage?.(installationId)
                } catch {
                    // Failing to seed state is non-fatal — the server falls back to UserIntegration
                    // membership detection. We surface the GitHub page either way.
                }
                window.open(manageInstallationUrl(installationId, accountType, accountName), '_blank')
            }}
            tooltip={repoNames.length > 0 ? 'Manage repository access on GitHub' : 'Configure repository access'}
        />
    ) : null

    if (loading && repoNames.length === 0) {
        return (
            <div className="flex items-center gap-1 text-xs text-muted min-h-5">
                <Spinner className="text-sm" />
                Loading repositories...
            </div>
        )
    }

    if (repoNames.length > 0) {
        return (
            <div className="flex items-center gap-2 min-h-5">
                <div className="text-xs text-muted">
                    <IconBranch className="inline mr-1 text-sm" />
                    {repoNames.length} repositor{repoNames.length === 1 ? 'y' : 'ies'} accessible:{' '}
                    {repoNames.length <= 3
                        ? repoNames.join(', ')
                        : `${repoNames.slice(0, 3).join(', ')} and ${repoNames.length - 3} more`}
                </div>
                {manageButton}
            </div>
        )
    }

    return (
        <div className="flex items-center gap-2 min-h-5">
            <div className="text-xs text-muted">
                <IconBranch className="inline mr-1 text-sm" />
                No repositories accessible
            </div>
            {manageButton}
        </div>
    )
}
