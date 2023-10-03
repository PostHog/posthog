import { SceneExport } from 'scenes/sceneTypes'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebDashboard'

export function WebAnalyticsScene(): JSX.Element {
    return <WebAnalyticsDashboard />
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
}
