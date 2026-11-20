import { IconGear } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { IconBranch } from 'lib/lemon-ui/icons'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { QuillGitHubRepoSummary } from './QuillGitHubRepoSummary'

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
    const quillSurface = useQuillSurface()

    const openManagePage = installationId
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
    const manageTooltip = repoNames.length > 0 ? 'Manage repository access on GitHub' : 'Configure repository access'

    const noun = repoNames.length === 1 ? 'repository' : 'repositories'
    const countLabel =
        repositorySelection === 'selected'
            ? `${repoNames.length} selected ${noun}`
            : `${repoNames.length} ${noun} accessible`
    const repoList =
        repoNames.length <= 3
            ? repoNames.join(', ')
            : `${repoNames.slice(0, 3).join(', ')} and ${repoNames.length - 3} more`

    if (quillSurface) {
        return (
            <QuillGitHubRepoSummary
                loading={loading}
                hasRepos={repoNames.length > 0}
                accountName={accountName}
                repositorySelection={repositorySelection}
                total={total}
                countLabel={countLabel}
                repoList={repoList}
                onManage={openManagePage}
                manageTooltip={manageTooltip}
            />
        )
    }

    const manageButton = openManagePage ? (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconGear />}
            onClick={openManagePage}
            tooltip={manageTooltip}
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
        return (
            <div className="flex items-center gap-2 min-h-5">
                <div className="text-xs text-muted">
                    <IconBranch className="inline mr-1 text-sm" />
                    {countLabel}: {repoList}
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
