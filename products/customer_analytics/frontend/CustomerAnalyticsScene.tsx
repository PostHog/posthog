import { useValues } from 'kea'

import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CustomerAnalyticsDashboardCard } from './CustomerAnalyticsDashboardCard'
import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

export const scene: SceneExport = {
    component: CustomerAnalyticsScene,
    logic: customerAnalyticsSceneLogic,
}

export function CustomerAnalyticsScene(): JSX.Element {
    const { newDashboardModalVisible } = useValues(customerAnalyticsSceneLogic)

    return (
        <SceneContent>
            <Header />
            <CustomerAnalyticsDashboardCard />
            {newDashboardModalVisible && <NewDashboardModal />}
        </SceneContent>
    )
}

const Header = (): JSX.Element => {
    return (
        <SceneTitleSection
            name={sceneConfigurations[Scene.CustomerAnalytics].name}
            description={sceneConfigurations[Scene.CustomerAnalytics].description}
            resourceType={{
                type: sceneConfigurations[Scene.CustomerAnalytics].iconType || 'default_icon_type',
            }}
        />
    )
}
