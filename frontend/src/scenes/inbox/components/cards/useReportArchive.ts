import clsx from 'clsx'
import { useState } from 'react'

import api from 'lib/api'

import { captureInboxReportAction, InboxReportActionSurface } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { DismissalReasonValue } from '../../utils/dismissalReasons'
import { openDismissReportDialog } from '../shell/DismissReportDialog'

/**
 * Shared archive handler for the inbox cards (Report / Pull request). Opens the dismissal
 * dialog and either delegates to the bound list logic via `onArchive` (optimistic) or, when
 * used standalone (e.g. stories), falls back to a direct `signalReports.setState` call. The
 * single-report `dismiss` analytics fire here so both the list card and the detail pane are
 * covered from one place.
 */
export function useReportArchive({
    reportId,
    cardTitle,
    report,
    surface,
    onArchive,
    onArchived,
}: {
    reportId: string
    cardTitle: string
    /** The report being archived, used to enrich the `dismiss` analytics. */
    report?: SignalReport | null
    /** Which surface the archive was triggered from, for the `dismiss` analytics. */
    surface?: InboxReportActionSurface
    onArchive?: (reason: DismissalReasonValue, note: string) => void
    /** Fired once the report is archived (after `onArchive`, or after the fallback API call succeeds). */
    onArchived?: () => void
}): { isArchiving: boolean; onArchiveClick: (event: React.MouseEvent) => void } {
    const [isArchiving, setIsArchiving] = useState(false)

    const onArchiveClick = (event: React.MouseEvent): void => {
        event.preventDefault()
        event.stopPropagation()
        openDismissReportDialog({
            reportTitle: cardTitle,
            onConfirm: async ({ reason, note }) => {
                // The structured reason plus the user's note — the note is the actionable signal
                // we want for tuning the agent, so it rides along with the dismiss event.
                captureInboxReportAction({
                    report: report ?? null,
                    actionType: 'dismiss',
                    surface: surface ?? 'list_row',
                    extra: { dismissal_reason: reason, ...(note ? { dismissal_note: note } : {}) },
                })
                if (onArchive) {
                    onArchive(reason, note)
                    onArchived?.()
                    return
                }
                // Fallback for standalone usage (e.g. stories) without a bound list logic.
                setIsArchiving(true)
                try {
                    await api.signalReports.setState(reportId, {
                        state: 'suppressed',
                        dismissal_reason: reason,
                        ...(note ? { dismissal_note: note } : {}),
                    })
                    onArchived?.()
                } finally {
                    setIsArchiving(false)
                }
            },
        })
    }

    return { isArchiving, onArchiveClick }
}

/**
 * Shared row className for inbox cards. Attached rows sit inside a single bordered container
 * (dividers between items); freestanding cards get their own border (dashed for reports).
 */
export function inboxCardRowClassName(attached: boolean, opts?: { dashed?: boolean }): string {
    return clsx(
        'group flex w-full flex-col gap-2.5 @lg:flex-row @lg:items-stretch @lg:gap-3 bg-surface-primary px-4 py-3.5 transition-all duration-150 hover:bg-surface-secondary',
        attached
            ? 'border-b border-primary last:border-b-0'
            : opts?.dashed
              ? 'rounded border border-dashed border-primary hover:border-secondary'
              : 'rounded border border-primary hover:border-secondary'
    )
}
