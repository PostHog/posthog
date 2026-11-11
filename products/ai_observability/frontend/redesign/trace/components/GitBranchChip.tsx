import { IconGitBranch } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { TraceGitApi, TracePullRequestApi } from '../../../generated/api.schemas'
import { LabeledChipValue } from './LabeledChipValue'

export interface GitBranchChipProps extends TraceGitApi {
    pullRequest: TracePullRequestApi | null
}

function tooltipTitle({ branch, repo, pullRequest }: GitBranchChipProps): string {
    const location = repo ? `Git branch ${branch} in ${repo}` : `Git branch ${branch}`
    if (!pullRequest) {
        return location
    }
    const title = pullRequest.title ? `: ${pullRequest.title}` : ''
    return `${location}. Opens pull request #${pullRequest.number} in engineering analytics${title}`
}

export function GitBranchChip(props: GitBranchChipProps): JSX.Element {
    const { branch, pullRequest } = props
    const tag = (
        <LemonTag weight="normal" data-attr="trace-view-git-branch-chip">
            <LabeledChipValue label="Branch" icon={<IconGitBranch />}>
                <span className="font-mono">{branch}</span>
            </LabeledChipValue>
        </LemonTag>
    )
    return (
        // The pull request arrives after the chip renders, which swaps the trigger element. The tooltip attaches its
        // hover listeners to the first element only, so it remounts for the new one.
        <Tooltip key={pullRequest ? 'linked' : 'plain'} title={tooltipTitle(props)}>
            {pullRequest ? (
                <Link
                    to={urls.engineeringAnalyticsPullRequest(
                        pullRequest.repoOwner,
                        pullRequest.repoName,
                        pullRequest.number
                    )}
                    subtle
                    className="inline-flex"
                    data-attr="trace-view-git-pull-request-link"
                >
                    {tag}
                </Link>
            ) : (
                tag
            )}
        </Tooltip>
    )
}
