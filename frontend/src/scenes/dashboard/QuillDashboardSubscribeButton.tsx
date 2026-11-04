import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { dashboardLogic } from './dashboardLogic'
import { SubscriptionCountBadge } from './SubscriptionCountBadge'

export function QuillDashboardSubscribeButton(): JSX.Element | null {
    const { dashboard, canEditDashboard, tiles } = useValues(dashboardLogic)
    const { push } = useActions(router)

    if (!dashboard || !canEditDashboard || tiles.length === 0) {
        return null
    }

    const dashboardId = dashboard.id

    return (
        <Button
            variant="default"
            data-attr="dashboard-subscribe-prominent-button"
            onClick={() => {
                posthog.capture('dashboard subscribe clicked', {
                    dashboard_id: dashboardId,
                })
                push(urlForSubscriptions({ dashboardId }))
            }}
        >
            <IconBell />
            Subscribe
            {/* Read the count only when the logic is already mounted, so a dashboard view does not load subscriptions */}
            {subscriptionsLogic.isMounted({ dashboardId }) && <SubscriptionCountBadge dashboardId={dashboardId} />}
        </Button>
    )
}
