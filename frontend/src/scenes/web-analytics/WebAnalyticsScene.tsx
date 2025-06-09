import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebAnalyticsDashboard'
import { WebAnalyticsHeaderButtons } from 'scenes/web-analytics/WebAnalyticsHeaderButtons'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

export function WebAnalyticsScene(): JSX.Element {
    return (
        <>
            <PageHeader buttons={<WebAnalyticsHeaderButtons />} />

            <WebAnalyticsDashboard />
        </>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
}
