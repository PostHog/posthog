import { IconGear } from '@posthog/icons'
import { LemonButton, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { IconBranch } from 'lib/lemon-ui/icons'

// The repository tooltip lists names inline; cap how many so a selected-scope installation with
// hundreds of repositories can't paint a tooltip taller than the viewport. The popup bounds its
// width, not its height, and a hover tooltip cannot scroll.
const REPO_TOOLTIP_LIMIT = 20

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
    repositorySelection,
    total,
    onBeforeManage,
}: {
    repoNames: string[]
    loading: boolean
    installationId?: string | null
    accountType?: string
    accountName?: string
    /** GitHub's own scope for the installation: "all" repositories or "selected" ones. */
    repositorySelection?: string | null
    /** Total repositories the installation can see, when known without listing them all. */
    total?: number | null
    /** Called before opening the GitHub installation settings page. Use this to seed
     * server-side state (via the `github_prepare_callback` endpoints) so the eventual
     * Setup URL callback can be dispatched to the right team/personal handler. */
    onBeforeManage?: (installationId: string) => Promise<void> | void
}): JSX.Element {
    // One opener for both controls. It seeds the server-side callback state (best-effort) before
    // opening the GitHub installation page, so the eventual Setup URL callback is routed to the right
    // team/personal handler. Both controls call this, so neither can reach GitHub with the state
    // unseeded.
    const openInstallation = installationId
        ? async (): Promise<void> => {
              try {
                  await onBeforeManage?.(installationId)
              } catch {
                  // Failing to seed state is non-fatal — the server falls back to UserIntegration
                  // membership detection. We surface the GitHub page either way.
              }
              window.open(manageInstallationUrl(installationId, accountType, accountName), '_blank')
          }
        : null

    const manageButton = openInstallation ? (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconGear />}
            onClick={openInstallation}
            tooltip={repoNames.length > 0 ? 'Manage repository access on GitHub' : 'Configure repository access'}
        />
    ) : null

    if (repositorySelection === 'all') {
        return (
            <div className="flex items-center gap-2 min-h-5">
                <div className="text-xs text-muted">
                    <IconBranch className="inline mr-1 text-sm" />
                    All repositories in {accountName || 'this account'}
                    {total != null ? ` (${total})` : ''}
                </div>
                {manageButton}
            </div>
        )
    }

    if (loading && repoNames.length === 0) {
        return (
            <div className="flex items-center gap-1 text-xs text-muted min-h-5">
                <Spinner className="text-sm" />
                Loading repositories...
            </div>
        )
    }

    if (repoNames.length > 0) {
        const noun = repoNames.length === 1 ? 'repository' : 'repositories'
        const countLabel =
            repositorySelection === 'selected'
                ? `${repoNames.length} selected ${noun}`
                : `${repoNames.length} ${noun} accessible`
        const hiddenCount = repoNames.length - 3
        // The overflow count reads as a link and opens the GitHub page that controls repository
        // access (its tooltip lists the accessible repositories, capped by REPO_TOOLTIP_LIMIT). It
        // routes through `openInstallation` as a link-styled button, not a bare anchor, so a modifier
        // or middle click can't reach GitHub before the callback state is seeded.
        const tooltipRepoNames =
            repoNames.length > REPO_TOOLTIP_LIMIT
                ? `${repoNames.slice(0, REPO_TOOLTIP_LIMIT).join(', ')}, and ${repoNames.length - REPO_TOOLTIP_LIMIT} more`
                : repoNames.join(', ')
        const overflow =
            hiddenCount > 0 ? (
                <>
                    {' '}
                    <Tooltip title={tooltipRepoNames}>
                        {openInstallation ? (
                            <Link onClick={openInstallation}>and {hiddenCount} more</Link>
                        ) : (
                            <span>and {hiddenCount} more</span>
                        )}
                    </Tooltip>
                </>
            ) : null
        return (
            <div className="flex items-center gap-2 min-h-5">
                <div className="text-xs text-muted">
                    <IconBranch className="inline mr-1 text-sm" />
                    {countLabel}: {repoNames.slice(0, 3).join(', ')}
                    {overflow}
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
