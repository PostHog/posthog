import './DashboardSubscribeButton.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { dashboardLogic } from './dashboardLogic'
import { QuillDashboardSubscribeButton } from './QuillDashboardSubscribeButton'

function SubscribeCountIcon({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { subscriptions } = useValues(subscriptionsLogic({ dashboardId }))

    return (
        <IconWithCount count={subscriptions?.length} showZero={false}>
            <IconBell className="DashboardSubscribeBell" fontSize="16" />
        </IconWithCount>
    )
}

function SubscribeIcon({ dashboardId }: { dashboardId: number }): JSX.Element {
    if (!subscriptionsLogic.isMounted({ dashboardId })) {
        return <IconBell className="DashboardSubscribeBell" fontSize="16" />
    }

    return <SubscribeCountIcon dashboardId={dashboardId} />
}

export function DashboardSubscribeButton(): JSX.Element | null {
    const { dashboard, canEditDashboard, tiles } = useValues(dashboardLogic)
    const { push } = useActions(router)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillDashboardSubscribeButton />
    }

    if (!dashboard || !canEditDashboard || tiles.length === 0) {
        return null
    }

    const dashboardId = dashboard.id

    return (
        <LemonButton
            type="tertiary"
            size="small"
            icon={<SubscribeIcon dashboardId={dashboardId} />}
            data-attr="dashboard-subscribe-prominent-button"
            onClick={() => {
                posthog.capture('dashboard subscribe clicked', {
                    dashboard_id: dashboardId,
                })
                push(urlForSubscriptions({ dashboardId }))
            }}
        >
            Subscribe
        </LemonButton>
    )
}
