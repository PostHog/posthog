import { useMaxTool } from 'scenes/max/useMaxTool'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebAnalyticsDashboard'
import { WebAnalyticsHeaderButtons } from 'scenes/web-analytics/WebAnalyticsHeaderButtons'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsSceneMenuBar } from 'scenes/web-analytics/WebAnalyticsSceneMenuBar'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

export function WebAnalyticsScene(): JSX.Element {
    useMaxTool({
        identifier: 'web_analytics_doctor',
        active: true,
        context: {},
        suggestions: [
            'Is my web analytics set up correctly?',
            'Why are my pageviews low?',
            'Diagnose my reverse proxy setup',
        ],
    })

    return (
        <>
            <SceneContent>
                <WebAnalyticsSceneMenuBar />
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WebAnalytics].name}
                    description={sceneConfigurations[Scene.WebAnalytics].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.WebAnalytics].iconType || 'default_icon_type',
                    }}
                    actions={<WebAnalyticsHeaderButtons />}
                />
                <WebAnalyticsDashboard />
            </SceneContent>
        </>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
    productKey: ProductKey.WEB_ANALYTICS,
}
