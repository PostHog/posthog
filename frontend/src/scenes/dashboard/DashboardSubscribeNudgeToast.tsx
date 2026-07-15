import { router } from 'kea-router'

import { IconBell } from '@posthog/icons'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { urlForSubscription } from 'products/subscriptions/frontend/components/Subscriptions/utils'

export function DashboardSubscribeNudgeToast({ dashboardName }: { dashboardName?: string | null }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 py-1 pr-1 min-w-0 items-start">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
                <IconBell className="size-4 shrink-0 text-primary" />
                <span>You keep coming back to {dashboardName || 'this dashboard'}</span>
            </div>
            <div className="text-xs text-secondary leading-snug">
                Get it delivered to your inbox every Monday instead of checking back.
            </div>
        </div>
    )
}

/** Sticky nudge toast: persists until the user clicks the CTA (which auto-dismisses) or the X. */
export function showDashboardSubscribeNudgeToast(dashboardId: number, dashboardName?: string | null): void {
    lemonToast.info(<DashboardSubscribeNudgeToast dashboardName={dashboardName} />, {
        toastId: `dashboard-subscribe-nudge-${dashboardId}`,
        autoClose: false,
        icon: false, // the body carries its own bell icon
        button: {
            label: 'Set up subscription',
            action: () =>
                router.actions.push(urlForSubscription('new', { dashboardId }), {
                    prefill: 'nudge',
                    via: 'toast',
                }),
            dataAttr: 'dashboard-subscribe-nudge-toast-cta',
        },
    })
}
