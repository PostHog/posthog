import { useValues } from 'kea'
import { useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { signalsReportsRefundCreate } from 'products/signals/frontend/generated/api'

import { captureInboxReportAction, InboxReportActionSurface } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { openRefundReportDialog } from '../shell/RefundReportDialog'

/**
 * Shared refund handler for the inbox cards and the detail pane, mirroring `useReportArchive`.
 * Opens the refund dialog and posts to the refund endpoint; the backend freezes the billing path,
 * archives the report, and (when needed) kicks off the billing credit. Offered only when the flag
 * is on and the report has a billable PR that hasn't been refunded — the server enforces the same
 * rules, so `canRefund` is purely a display gate.
 */
export function useReportRefund({
    report,
    surface,
    onRefunded,
}: {
    report: SignalReport
    /** Which surface the refund was triggered from, for the `refund` analytics. */
    surface?: InboxReportActionSurface
    /** Fired once the refund API call succeeds (the report is archived server-side by then). */
    onRefunded?: () => void
}): { canRefund: boolean; isRefunding: boolean; onRefundClick: (event: React.MouseEvent) => void } {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    const [isRefunding, setIsRefunding] = useState(false)

    // Exempt reports ("Free" tag) were never charged, so there is nothing to refund; a report
    // without a PR was never billed either. One refund per report, ever.
    const canRefund =
        !!featureFlags[FEATURE_FLAGS.SIGNALS_PR_REFUNDS] &&
        !!report.implementation_pr_url &&
        !report.refund &&
        !report.billing_exempt_reason

    const onRefundClick = (event: React.MouseEvent): void => {
        event.preventDefault()
        event.stopPropagation()
        openRefundReportDialog({
            reportTitle: report.title,
            onConfirm: async ({ reason, note }) => {
                if (isRefunding || currentTeamId == null) {
                    return
                }
                setIsRefunding(true)
                try {
                    await signalsReportsRefundCreate(String(currentTeamId), report.id, {
                        reason,
                        ...(note ? { note } : {}),
                    })
                    captureInboxReportAction({
                        report,
                        actionType: 'refund',
                        surface: surface ?? 'list_row',
                        extra: { refund_reason: reason, ...(note ? { refund_note: note } : {}) },
                    })
                    lemonToast.success("PR refunded – you won't be charged for it")
                    onRefunded?.()
                } catch (error: any) {
                    lemonToast.error(error?.detail || error?.error || error?.message || 'Failed to refund this PR')
                    throw error // keep the dialog open so the user can retry
                } finally {
                    setIsRefunding(false)
                }
            },
        })
    }

    return { canRefund, isRefunding, onRefundClick }
}
