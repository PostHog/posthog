import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ActiveUsersInsights } from './components/Insights/ActiveUsersInsights'
import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

export const scene: SceneExport = {
    component: CustomerAnalyticsScene,
    logic: customerAnalyticsSceneLogic,
}

export function CustomerAnalyticsScene({ tabId }: { tabId?: string }): JSX.Element {
    if (!tabId) {
        throw new Error('CustomerAnalyticsScene was rendered with no tabId')
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.CustomerAnalytics].name}
                description={sceneConfigurations[Scene.CustomerAnalytics].description}
                resourceType={{
                    type: sceneConfigurations[Scene.CustomerAnalytics].iconType || 'default_icon_type',
                }}
            />
            <div className="space-y-2">
                <ActiveUsersInsights />
            </div>
        </SceneContent>
    )
}
