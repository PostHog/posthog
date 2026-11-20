import { IconChevronDown } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

import { accountLabel, sourceLabel } from './githubInstallationLabels'

export function QuillGitHubInstallationLink({
    installations,
    loading,
    onLink,
    projectName,
    emphasizeInstallation = false,
    personalGithubLogin,
    onVisibilityChange,
}: {
    installations: GitHubAvailableInstallationApi[]
    personalGithubLogin?: string | null
    onVisibilityChange?: (visible: boolean) => void
    loading: boolean
    onLink: (installationId?: string) => void
    projectName?: string
    emphasizeInstallation?: boolean
}): JSX.Element | null {
    if (installations.length === 0) {
        return null
    }

    const variant = emphasizeInstallation ? 'primary' : 'outline'

    if (installations.length === 1) {
        // Always name the installation, even when there's only one to pick. Omitting it asks the
        // backend to auto-resolve from a sibling project, which an orphan installation has none of.
        return (
            <Button variant={variant} loading={loading} onClick={() => onLink(installations[0].installation_id)}>
                {emphasizeInstallation
                    ? `Connect ${accountLabel(installations[0])}`
                    : `Connect to ${projectName ?? 'this project'}`}
            </Button>
        )
    }

    return (
        <DropdownMenu onOpenChange={(open) => onVisibilityChange?.(open)}>
            <DropdownMenuTrigger render={<Button variant={variant} loading={loading} />}>
                {emphasizeInstallation ? 'Choose an existing installation' : 'Choose an account'}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                {installations.map((installation) => (
                    <DropdownMenuItem
                        key={installation.installation_id}
                        description={sourceLabel(installation, personalGithubLogin)}
                        disabledReason={loading ? 'Connecting an account' : undefined}
                        onClick={() => onLink(installation.installation_id)}
                    >
                        {accountLabel(installation)}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
