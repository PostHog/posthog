import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import posthog from 'lib/posthog-typed'
import { userLogic } from 'scenes/userLogic'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscription } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { dashboardLogic } from './dashboardLogic'
import { dashboardSubscribeNudgeLogic } from './dashboardSubscribeNudgeLogic'

export function DashboardSubscribeNudge(): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic)

    if (!dashboard?.id) {
        return null
    }

    return <DashboardSubscribeNudgeCandidate dashboardId={dashboard.id} />
}

// Split out so subscriptions are only fetched for dashboards already past the view threshold —
// the vast majority of dashboard views never reach this point, so most views never trigger a
// subscriptions-list fetch just to feed this banner's eligibility check.
function DashboardSubscribeNudgeCandidate({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { isCandidate } = useValues(dashboardSubscribeNudgeLogic({ dashboardId }))

    if (!isCandidate) {
        return null
    }

    return <DashboardSubscribeNudgeBanner dashboardId={dashboardId} />
}

function DashboardSubscribeNudgeBanner({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const logic = dashboardSubscribeNudgeLogic({ dashboardId })
    const { showNudge, viewCount7d } = useValues(logic)
    const { dismiss, setHasExistingSubscription } = useActions(logic)
    const { subscriptions, subscriptionsLoading } = useValues(subscriptionsLogic({ dashboardId }))
    const { dashboard } = useValues(dashboardLogic)
    const { setSubscriptionPrefill } = useActions(dashboardLogic)
    const { user } = useValues(userLogic)
    const { push } = useActions(router)

    useEffect(() => {
        if (!subscriptionsLoading) {
            setHasExistingSubscription(subscriptions.length > 0)
        }
    }, [subscriptionsLoading, subscriptions.length, setHasExistingSubscription])

    if (!showNudge) {
        return null
    }

    const handleSubscribeClick = (): void => {
        posthog.capture('dashboard subscribe nudge clicked', {
            dashboard_id: dashboardId,
            view_count_7d: viewCount7d,
            prefilled: true,
        })
        // Frequency (weekly), day (Monday), time (morning), and destination (email) already match
        // the subscription form's own defaults — only the recipient needs prefilling here.
        setSubscriptionPrefill({
            title: `${dashboard?.name || 'Dashboard'} weekly digest`,
            ...(user?.email ? { target_value: user.email } : {}),
        })
        push(urlForSubscription('new', { dashboardId }))
    }

    return (
        <LemonBanner
            type="info"
            className="mt-4 mb-2"
            onClose={dismiss}
            action={{
                children: 'Set up subscription',
                onClick: handleSubscribeClick,
                'data-attr': 'dashboard-subscribe-nudge-cta',
            }}
        >
            You've viewed this dashboard several times this week. Get it delivered to your inbox every Monday instead of
            checking back.
        </LemonBanner>
    )
}
