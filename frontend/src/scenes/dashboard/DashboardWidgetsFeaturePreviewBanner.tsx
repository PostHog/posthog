import { router } from 'kea-router'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { dashboardWidgetsFeaturePreviewUrl } from './dashboardWidgetsFeaturePreview'

export function DashboardWidgetsFeaturePreviewBanner(): JSX.Element {
    return (
        <LemonBanner
            type="info"
            action={{
                children: 'Enable in feature previews',
                onClick: () => router.actions.push(dashboardWidgetsFeaturePreviewUrl()),
            }}
        >
            Dashboard widgets are in beta. Enable the preview to add widgets like top error tracking issues and recent
            session recordings to your dashboards.
        </LemonBanner>
    )
}
