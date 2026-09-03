import type { PullRequestCiStatusEnumApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalReportStatus } from 'products/signals/frontend/inbox/types'

export const PR_BADGE_STATE = {
    open: {
        label: 'Open',
        className: 'border-success bg-success-highlight text-success',
        hoverClassName:
            'hover:border-success-dark hover:text-success-dark dark:hover:border-success-light dark:hover:text-success-light',
    },
    merged: {
        label: 'Merged',
        className:
            'border-[var(--color-purple-600)] bg-[color-mix(in_oklab,var(--color-purple-600)_10%,transparent)] text-[var(--color-purple-700)] dark:border-[var(--color-purple-400)] dark:bg-[color-mix(in_oklab,var(--color-purple-400)_10%,transparent)] dark:text-[var(--color-purple-300)]',
        hoverClassName:
            'hover:border-[var(--color-purple-800)] hover:text-[var(--color-purple-800)] dark:hover:border-[var(--color-purple-200)] dark:hover:text-[var(--color-purple-200)]',
    },
    closed: {
        label: 'Closed',
        className: 'border-danger bg-danger-highlight text-danger',
        hoverClassName:
            'hover:border-danger-dark hover:text-danger-dark dark:hover:border-danger-light dark:hover:text-danger-light',
    },
}

export type PrBadgeState = keyof typeof PR_BADGE_STATE

export function derivePrState(status: SignalReportStatus | string, prMerged: boolean): PrBadgeState {
    if (prMerged) {
        return 'merged'
    }
    // A terminal report no longer points at an open PR: dismiss and resolve close the report's open
    // implementation PR, a report suppressed by its PR closing without merging is closed by
    // definition, and a failed report's PR never landed. Only a live report still has an open PR.
    if (
        status === SignalReportStatus.FAILED ||
        status === SignalReportStatus.SUPPRESSED ||
        status === SignalReportStatus.RESOLVED
    ) {
        return 'closed'
    }
    return 'open'
}

/**
 * The CI states the pill says something about, and the words and color each gets. A head commit with
 * no checks (`none`) and a status GitHub could not answer for both mean there is nothing to report,
 * so neither draws a glyph. An absent glyph never claims a pull request is green.
 */
export const PR_CI_GLYPH = {
    passing: { label: 'checks passing', className: 'text-success' },
    failing: { label: 'checks failing', className: 'text-danger' },
    pending: { label: 'checks running', className: 'text-warning' },
}

export type PrCiGlyphStatus = keyof typeof PR_CI_GLYPH

/** The glyph an open pull request's CI state earns, or null when there is nothing to show. */
export function prCiGlyphStatus(
    state: PrBadgeState,
    ciStatus?: PullRequestCiStatusEnumApi | null
): PrCiGlyphStatus | null {
    // Only an open pull request has CI a reader can act on; on a merged or closed one it is history.
    if (state !== 'open' || !ciStatus || !(ciStatus in PR_CI_GLYPH)) {
        return null
    }
    return ciStatus as PrCiGlyphStatus
}
