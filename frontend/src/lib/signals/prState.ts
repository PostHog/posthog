import type { LemonTagType } from '@posthog/lemon-ui'

import { SignalReportStatus } from '~/scenes/inbox/types'

/**
 * PR open/merged/closed state, mapped to muted palette tags (outlined: --success / --purple /
 * --danger). "merged" comes from `implementation_pr_merged`, the flag the GitHub webhook sets on
 * merge — report status can't stand in for it, since a report can be resolved directly without its
 * PR ever landing. A failed report means the PR never landed; everything else is still an open PR.
 *
 * Shared so every surface that shows a report's PR agrees on what its state means, including the
 * support ticket sidebar, where "did this ship?" is the question a teammate is answering.
 */
export const PR_BADGE_STATE: Record<'open' | 'merged' | 'closed', { label: string; type: LemonTagType }> = {
    open: { label: 'open', type: 'success' },
    merged: { label: 'merged', type: 'completion' },
    closed: { label: 'closed', type: 'danger' },
}

export type PrBadgeState = keyof typeof PR_BADGE_STATE

/** `status` is widened to string so callers holding the generated API enum can pass it directly. */
export function derivePrState(status: SignalReportStatus | string, prMerged: boolean): PrBadgeState {
    if (prMerged) {
        return 'merged'
    }
    if (status === SignalReportStatus.FAILED) {
        return 'closed'
    }
    return 'open'
}
