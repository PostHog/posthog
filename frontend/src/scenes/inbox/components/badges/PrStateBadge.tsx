import { IconPullRequest } from '@posthog/icons'
import { LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { SignalReportStatus } from '../../types'

/**
 * PR open/merged/closed state, mapped to muted palette tags (outlined: --success / --purple /
 * --danger). We have no real PR status from GitHub on the report, so it's inferred from the
 * report status: a resolved report means its implementation PR merged (webhook-driven on merge),
 * a failed one means the PR never landed, everything else is still an open PR.
 */
const PR_BADGE_STATE: Record<'open' | 'merged' | 'closed', { label: string; type: LemonTagType }> = {
    open: { label: 'open', type: 'success' },
    merged: { label: 'merged', type: 'completion' },
    closed: { label: 'closed', type: 'danger' },
}

export type PrBadgeState = keyof typeof PR_BADGE_STATE

export function derivePrState(status: SignalReportStatus): PrBadgeState {
    if (status === SignalReportStatus.RESOLVED) {
        return 'merged'
    }
    if (status === SignalReportStatus.FAILED) {
        return 'closed'
    }
    return 'open'
}

/**
 * PR status badge: a state-colored tag with the pull-request icon and `#1234`. When a PR URL is
 * known the whole badge is the GitHub link itself. Rendered in both the list card's top-right
 * corner and the report detail header.
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
