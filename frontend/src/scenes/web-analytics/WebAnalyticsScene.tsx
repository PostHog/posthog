import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebAnalyticsDashboard'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsMenu } from 'scenes/web-analytics/WebAnalyticsMenu'

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
