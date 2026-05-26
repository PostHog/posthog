import { useActions } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DashboardPlacement, DashboardType, QueryBasedInsightModel } from '~/types'

const DASHBOARD_PUBLIC_ACCESS_BANNER_PLACEMENTS = [
    DashboardPlacement.Dashboard,
    DashboardPlacement.ProjectHomepage,
    DashboardPlacement.Builtin,
]

export function DashboardPublicAccessBanner({
    dashboard,
    placement,
}: {
    dashboard: DashboardType<QueryBasedInsightModel> | null
    placement: DashboardPlacement
}): JSX.Element | null {
    const { push } = useActions(router)

    if (!dashboard?.is_shared || !DASHBOARD_PUBLIC_ACCESS_BANNER_PLACEMENTS.includes(placement)) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            className="mb-4"
            dismissKey={`dashboard-public-access-banner-${dashboard.id}`}
            action={{
                children: 'Manage sharing',
                onClick: () => push(urls.dashboardSharing(dashboard.id)),
            }}
        >
            This dashboard is shared publicly. Updates you make here may be visible to anyone with the public link.
            Avoid adding sensitive data.
        </LemonBanner>
    )
}
