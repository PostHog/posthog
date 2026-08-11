import { IconPullRequest, type IconProps } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { PR_BADGE_STATE, type PrBadgeState } from './prState'

function IconGitMerge(props: IconProps): JSX.Element {
    return (
        <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false" {...props}>
            <path d="M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5h1.378a2.251 2.251 0 1 1 0 1.5H9.25A5.734 5.734 0 0 1 5 7.123v3.505a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.95-.218ZM4.25 13.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm8.5-4.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5ZM5 3.25a.75.75 0 1 0 0 .005V3.25Z" />
        </svg>
    )
}

function IconGitPullRequestClosed(props: IconProps): JSX.Element {
    return (
        <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false" {...props}>
            <path d="M3.25 1A2.25 2.25 0 0 1 4 5.372v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.251 2.251 0 0 1 3.25 1Zm9.5 5.5a.75.75 0 0 1 .75.75v3.378a2.251 2.251 0 1 1-1.5 0V7.25a.75.75 0 0 1 .75-.75Zm-2.03-5.273a.75.75 0 0 1 1.06 0l.97.97.97-.97a.748.748 0 0 1 1.265.332.75.75 0 0 1-.205.729l-.97.97.97.97a.751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018l-.97-.97-.97.97a.749.749 0 0 1-1.275-.326.749.749 0 0 1 .215-.734l.97-.97-.97-.97a.75.75 0 0 1 0-1.06ZM2.5 3.25a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0ZM3.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm9.5 0a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z" />
        </svg>
    )
}

export function PrBadge({
    prNumber,
    prUrl,
    state,
}: {
    prNumber: string
    prUrl?: string | null
    state: PrBadgeState
}): JSX.Element {
    const { label, className, hoverClassName } = PR_BADGE_STATE[state]
    const StateIcon =
        state === 'merged' ? IconGitMerge : state === 'closed' ? IconGitPullRequestClosed : IconPullRequest
    const badge = (
        <span
            className={cn(
                'inline-flex h-5 items-center gap-1 rounded-full border px-1.5 text-xs font-medium transition-colors',
                className,
                prUrl && `cursor-pointer ${hoverClassName}`
            )}
        >
            <StateIcon className="size-3" />
            <span className="font-mono tabular-nums">#{prNumber}</span>
        </span>
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
                className="no-underline"
            >
                {badge}
            </Link>
        </Tooltip>
    )
}
