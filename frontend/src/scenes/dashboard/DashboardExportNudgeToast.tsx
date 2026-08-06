import { router } from 'kea-router'

import { IconCalendar } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    SUBSCRIPTION_PREFILL_PARAMS,
    urlForSubscription,
} from 'products/subscriptions/frontend/components/Subscriptions/utils'

export function dashboardExportNudgeToastId(dashboardId: number): string {
    return `dashboard-export-nudge-${dashboardId}`
}

// Deliberately free of any kea logic dependency: the sticky toast can outlive the dashboard scene,
// so the CTA only touches globals — the router and the toast itself.
export function onDashboardExportNudgeToastCta(dashboardId: number): void {
    lemonToast.dismiss(dashboardExportNudgeToastId(dashboardId))
    router.actions.push(urlForSubscription('new', { dashboardId }), {
        [SUBSCRIPTION_PREFILL_PARAMS.param]: SUBSCRIPTION_PREFILL_PARAMS.nudge,
        [SUBSCRIPTION_PREFILL_PARAMS.viaParam]: SUBSCRIPTION_PREFILL_PARAMS.viaExport,
    })
}

export function DashboardExportNudgeToast({
    dashboardId,
    dashboardName,
}: {
    dashboardId: number
    dashboardName?: string | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 py-1 pr-1 min-w-0 items-start">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
                <IconCalendar className="size-4 shrink-0 text-primary" />
                <span>Want this export on a schedule?</span>
            </div>
            <div className="text-xs text-secondary leading-snug">
                We can email or Slack {dashboardName || 'this dashboard'} to you every week, so you don't have to export
                it by hand.
            </div>
            <LemonButton
                type="primary"
                size="small"
                data-attr="dashboard-export-nudge-toast-cta"
                onClick={() => onDashboardExportNudgeToastCta(dashboardId)}
            >
                Set up recurring updates
            </LemonButton>
        </div>
    )
}

/** Sticky nudge toast: persists until the user clicks the CTA (which dismisses it) or the X. */
export function showDashboardExportNudgeToast(dashboardId: number, dashboardName: string | null | undefined): void {
    lemonToast.info(<DashboardExportNudgeToast dashboardId={dashboardId} dashboardName={dashboardName} />, {
        toastId: dashboardExportNudgeToastId(dashboardId),
        autoClose: false,
        icon: false, // the body carries its own icon
    })
}
