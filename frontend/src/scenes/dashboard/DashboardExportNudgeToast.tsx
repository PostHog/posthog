import { router } from 'kea-router'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { ExportNudgeCandidate, claimExportNudge } from 'scenes/dashboard/dashboardExportNudgeLogic'

import {
    SUBSCRIPTION_PREFILL_PARAMS,
    urlForSubscription,
} from 'products/subscriptions/frontend/components/Subscriptions/utils'

// Deliberately free of any kea logic dependency: the sticky toast can outlive the dashboard scene,
// so the CTA only touches globals — the router and the toast itself.
export function onDashboardExportNudgeToastCta(dashboardId: number, toastId: string): void {
    lemonToast.dismiss(toastId)
    router.actions.push(urlForSubscription('new', { dashboardId }), {
        [SUBSCRIPTION_PREFILL_PARAMS.param]: SUBSCRIPTION_PREFILL_PARAMS.nudge,
        [SUBSCRIPTION_PREFILL_PARAMS.viaParam]: SUBSCRIPTION_PREFILL_PARAMS.viaExport,
    })
}

/**
 * The export-complete message with the subscribe nudge folded into it, so an eligible exporter gets
 * one toast rather than a second one landing on top of the first. Returns null when this exporter
 * isn't in the treatment, leaving the caller its plain completion message.
 */
export function exportCompleteNudgeMessage(
    candidate: ExportNudgeCandidate | null,
    toastId: string
): JSX.Element | null {
    if (!candidate || !claimExportNudge(candidate.dashboardId)) {
        return null
    }

    return (
        <span className="flex flex-col items-start gap-1.5 min-w-0">
            <span>Export complete!</span>
            <span className="text-xs text-secondary leading-snug">
                Want this on a schedule? We can email or Slack {candidate.dashboardName || 'this dashboard'} to you
                every week.
            </span>
            <LemonButton
                type="primary"
                size="small"
                data-attr="dashboard-export-nudge-toast-cta"
                onClick={() => onDashboardExportNudgeToastCta(candidate.dashboardId, toastId)}
            >
                Set up recurring updates
            </LemonButton>
        </span>
    )
}
