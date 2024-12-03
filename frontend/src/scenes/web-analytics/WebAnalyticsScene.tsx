import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsMenu } from 'scenes/web-analytics/WebAnalyticsMenu'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebDashboard'

export function WebAnalyticsScene(): JSX.Element {
    return (
        <>
            <PageHeader buttons={<WebAnalyticsMenu />} />

            <WebAnalyticsDashboard />
        </>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
}
