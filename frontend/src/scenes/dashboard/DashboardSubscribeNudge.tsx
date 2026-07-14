import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { dashboardLogic } from './dashboardLogic'
import { dashboardSubscribeNudgeDismissKey, dashboardSubscribeNudgeLogic } from './dashboardSubscribeNudgeLogic'

export function DashboardSubscribeNudge(): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic)

    if (!dashboard?.id) {
        return null
    }

    return <DashboardSubscribeNudgeBanner dashboardId={dashboard.id} />
}

function DashboardSubscribeNudgeBanner({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const logic = dashboardSubscribeNudgeLogic({ dashboardId })
    const { showNudge } = useValues(logic)
    const { subscribeClicked } = useActions(logic)

    if (!showNudge) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className="mt-4 mb-2"
            dismissKey={dashboardSubscribeNudgeDismissKey(dashboardId)}
            action={{
                children: 'Set up subscription',
                onClick: subscribeClicked,
                'data-attr': 'dashboard-subscribe-nudge-cta',
            }}
        >
            You've viewed this dashboard several times in the last week. Get it delivered to your inbox every Monday
            instead of checking back.
        </LemonBanner>
    )
}
