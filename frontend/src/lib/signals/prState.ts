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
    if (status === SignalReportStatus.FAILED) {
        return 'closed'
    }
    return 'open'
}
