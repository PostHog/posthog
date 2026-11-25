import { IconGear } from '@posthog/icons'
import { Button, Spinner, Text } from '@posthog/quill'

import { IconBranch } from 'lib/lemon-ui/icons'

export function QuillGitHubRepoSummary({
    loading,
    hasRepos,
    accountName,
    repositorySelection,
    total,
    countLabel,
    repoList,
    onManage,
    manageTooltip,
}: {
    loading: boolean
    hasRepos: boolean
    accountName?: string
    repositorySelection?: string | null
    total?: number | null
    countLabel: string
    repoList: string
    onManage: (() => Promise<void>) | null
    manageTooltip: string
}): JSX.Element {
    if (loading && !hasRepos && repositorySelection !== 'all') {
        return (
            <Text size="xs" variant="muted" render={<span className="flex min-h-5 items-center gap-1" />}>
                <Spinner />
                Loading repositories...
            </Text>
        )
    }

    const summary =
        repositorySelection === 'all'
            ? `All repositories in ${accountName || 'this account'}${total != null ? ` (${total})` : ''}`
            : hasRepos
              ? `${countLabel}: ${repoList}`
              : 'No repositories accessible'

    return (
        <div className="flex min-h-5 items-center gap-2">
            <Text size="xs" variant="muted" render={<span className="flex min-w-0 items-center gap-1" />}>
                <IconBranch className="shrink-0" />
                <span>{summary}</span>
            </Text>
            {onManage ? (
                <Button
                    variant="outline"
                    size="icon-xs"
                    aria-label={manageTooltip}
                    tooltip={manageTooltip}
                    onClick={() => void onManage()}
                >
                    <IconGear />
                </Button>
            ) : null}
        </div>
    )
}
