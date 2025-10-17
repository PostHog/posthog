import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebAnalyticsDashboard'
import { WebAnalyticsHeaderButtons } from 'scenes/web-analytics/WebAnalyticsHeaderButtons'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export function WebAnalyticsScene(): JSX.Element {
    return (
        <>
            <SceneContent>
                <div className="flex flex-col gap-4">
                    <SceneTitleSection
                        name={sceneConfigurations[Scene.WebAnalytics].name}
                        description={sceneConfigurations[Scene.WebAnalytics].description}
                        resourceType={{
                            type: sceneConfigurations[Scene.WebAnalytics].iconType || 'default_icon_type',
                        }}
                        actions={<WebAnalyticsHeaderButtons />}
                    />
                    <SceneDivider />
                </div>
                <WebAnalyticsDashboard />
            </SceneContent>
        </>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
    settingSectionId: 'environment-web-analytics',
}
