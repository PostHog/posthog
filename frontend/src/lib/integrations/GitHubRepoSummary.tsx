import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable, LemonTableColumns, Link, Spinner } from '@posthog/lemon-ui'

import { IconBranch } from 'lib/lemon-ui/icons'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

function manageInstallationUrl(installationId: string, accountType?: string, accountName?: string): string {
    return accountType === 'Organization' && accountName
        ? `https://github.com/organizations/${accountName}/settings/installations/${installationId}`
        : `https://github.com/settings/installations/${installationId}`
}

const repoColumns: LemonTableColumns<GitHubRepoApi> = [
    {
        title: 'Repository',
        dataIndex: 'full_name',
        sorter: (a, b) => a.full_name.localeCompare(b.full_name),
        render: (_, repo) => (
            <Link to={`https://github.com/${repo.full_name}`} target="_blank">
                {repo.full_name}
            </Link>
        ),
    },
]

export function GitHubRepoSummary({
    repos,
    loading,
    installationId,
    accountType,
    accountName,
}: {
    repos: GitHubRepoApi[]
    loading: boolean
    installationId?: string | null
    accountType?: string
    accountName?: string
}): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const repoNames = repos.map((r) => r.name)

    const manageButton = installationId ? (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconGear />}
            onClick={() => window.open(manageInstallationUrl(installationId, accountType, accountName), '_blank')}
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
                    {repoNames.length <= 3 ? (
                        repoNames.join(', ')
                    ) : (
                        <>
                            {repoNames.slice(0, 3).join(', ')} and{' '}
                            <Link subtle className="underline" onClick={() => setIsModalOpen(true)}>
                                {repoNames.length - 3} more
                            </Link>
                        </>
                    )}
                </div>
                {manageButton}
                <LemonModal
                    isOpen={isModalOpen}
                    onClose={() => setIsModalOpen(false)}
                    title="Accessible repositories"
                    width={600}
                >
                    <LemonTable dataSource={repos} columns={repoColumns} rowKey="id" size="small" />
                </LemonModal>
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
