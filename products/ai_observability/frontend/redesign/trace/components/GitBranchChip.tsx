import { IconGitBranch } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { TraceGitApi } from '../../../generated/api.schemas'

export type GitBranchChipProps = TraceGitApi

export function GitBranchChip({ branch, repo }: GitBranchChipProps): JSX.Element {
    return (
        <Tooltip title={repo ? `Git branch ${branch} in ${repo}` : `Git branch ${branch}`}>
            <LemonTag icon={<IconGitBranch />} weight="normal" data-attr="trace-view-git-branch-chip">
                <span className="block max-w-60 truncate font-mono">{branch}</span>
            </LemonTag>
        </Tooltip>
    )
}
