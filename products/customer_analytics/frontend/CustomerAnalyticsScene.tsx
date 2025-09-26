import { useValues } from 'kea'

import { IconPeople } from '@posthog/icons'

import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
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
        <>
            <SceneTitleSection
                name="Customer analytics"
                description="Analyze your customers"
                resourceType={{
                    type: 'customerAnalytics',
                    forceIcon: <IconPeople />,
                }}
            />
            <SceneDivider />
        </>
    )
}
