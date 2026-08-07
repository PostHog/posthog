import { router } from 'kea-router'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ToastButton, lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
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

export type ExportNudgeRenderer = (headline: string, secondaryAction?: ToastButton) => JSX.Element

/** Claims the nudge once; the returned renderer may be called for each toast state. */
export function claimExportNudgeMessage(
    candidate: ExportNudgeCandidate | null,
    toastId: string
): ExportNudgeRenderer | null {
    if (!candidate || !claimExportNudge(candidate.dashboardId)) {
        return null
    }

    return (headline: string, secondaryAction?: ToastButton) => (
        <span className="flex flex-col items-start gap-1.5 min-w-0">
            <span>{headline}</span>
            <span className="text-xs text-secondary leading-snug">
                Want this on a schedule? We can send you a copy of{' '}
                <span className="italic">{candidate.dashboardName || 'this dashboard'}</span> every week.
            </span>
            {/* The toast body gives every button a horizontal margin, which pulls this row off the
                text above it and inflates the gap between the two buttons. */}
            <span className="flex items-center gap-2 *:m-0!">
                <LemonButton
                    type="primary"
                    size="small"
                    data-attr="dashboard-export-nudge-toast-cta"
                    onClick={() => onDashboardExportNudgeToastCta(candidate.dashboardId, toastId)}
                >
                    Set up recurring updates
                </LemonButton>
                {secondaryAction && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        data-attr={secondaryAction.dataAttr}
                        className={secondaryAction.className}
                        // Deliberately leaves the toast up, unlike ToastContent's own button slot: a
                        // side trip to the exports panel must not silently take the nudge with it.
                        onClick={() => void secondaryAction.action()}
                    >
                        {secondaryAction.label}
                    </LemonButton>
                )}
            </span>
        </span>
    )
}
