import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export interface OpenDashboardLinkProps {
    dashboardId: number | null
}

export function OpenDashboardLink({ dashboardId }: OpenDashboardLinkProps): JSX.Element | null {
    if (dashboardId === null) {
        return null
    }
    return (
        <LemonButton
            type="tertiary"
            size="small"
            to={urls.dashboard(dashboardId)}
            // pinned: data-attrs feed autocapture; dashboards and tests find the link by this value
            data-attr="home-open-dashboard"
        >
            Old dashboard
        </LemonButton>
    )
}
