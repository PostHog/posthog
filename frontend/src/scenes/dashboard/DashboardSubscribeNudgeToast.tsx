import { router } from 'kea-router'

import { IconBell } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    SUBSCRIPTION_PREFILL_PARAMS,
    urlForSubscription,
} from 'products/subscriptions/frontend/components/Subscriptions/utils'

export function dashboardSubscribeNudgeToastId(dashboardId: number): string {
    return `dashboard-subscribe-nudge-${dashboardId}`
}

// Deliberately free of any kea logic dependency: the sticky toast can outlive the dashboard
// scene (and its keyed logic), so the CTA only touches globals — the router and the toast itself.
export function onDashboardSubscribeNudgeToastCta(dashboardId: number): void {
    lemonToast.dismiss(dashboardSubscribeNudgeToastId(dashboardId))
    router.actions.push(urlForSubscription('new', { dashboardId }), {
        [SUBSCRIPTION_PREFILL_PARAMS.param]: SUBSCRIPTION_PREFILL_PARAMS.nudge,
        [SUBSCRIPTION_PREFILL_PARAMS.viaParam]: SUBSCRIPTION_PREFILL_PARAMS.viaToast,
    })
}

export function DashboardSubscribeNudgeToast({
    dashboardId,
    dashboardName,
    viewCount7d,
}: {
    dashboardId: number
    dashboardName?: string | null
    viewCount7d: number
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 py-1 pr-1 min-w-0 items-start">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
                <IconBell className="size-4 shrink-0 text-primary" />
                <span>You keep coming back to {dashboardName || 'this dashboard'}</span>
            </div>
            <div className="text-xs text-secondary leading-snug">
                You've viewed it {viewCount7d} times in the last week. Get it delivered to your inbox every Monday
                instead.
            </div>
            <LemonButton
                type="primary"
                size="small"
                data-attr="dashboard-subscribe-nudge-toast-cta"
                onClick={() => onDashboardSubscribeNudgeToastCta(dashboardId)}
            >
                Set up subscription
            </LemonButton>
        </div>
    )
}

/** Sticky nudge toast: persists until the user clicks the CTA (which dismisses it) or the X. */
export function showDashboardSubscribeNudgeToast(
    dashboardId: number,
    dashboardName: string | null | undefined,
    viewCount7d: number
): void {
    lemonToast.info(
        <DashboardSubscribeNudgeToast
            dashboardId={dashboardId}
            dashboardName={dashboardName}
            viewCount7d={viewCount7d}
        />,
        {
            toastId: dashboardSubscribeNudgeToastId(dashboardId),
            autoClose: false,
            icon: false, // the body carries its own bell icon
        }
    )
}
