import { IconPullRequest } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { PR_BADGE_STATE, type PrBadgeState } from './prState'

/**
 * PR status badge for the card's top-right corner: a state-colored tag with the pull-request
 * icon and `#1234`. When a PR URL is known the whole badge is the GitHub link itself.
 */
export function PrBadge({
    prNumber,
    prUrl,
    state,
}: {
    prNumber: string
    prUrl?: string | null
    state: PrBadgeState
}): JSX.Element {
    const { label, type } = PR_BADGE_STATE[state]
    const badge = (
        <LemonTag type={type} size="small" icon={<IconPullRequest />} className="font-mono tabular-nums">
            #{prNumber}
        </LemonTag>
    )

    if (!prUrl) {
        return <Tooltip title={`Pull request #${prNumber} (${label})`}>{badge}</Tooltip>
    }

    return (
        <Tooltip title={`Open pull request #${prNumber} (${label}) on GitHub`}>
            <Link
                to={prUrl}
                target="_blank"
                disableClientSideRouting
                onClick={(e) => e.stopPropagation()}
                aria-label={`Open pull request #${prNumber} (${label}) on GitHub`}
            >
                {badge}
            </Link>
        </Tooltip>
    )
}
