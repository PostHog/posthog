import { BindLogic, useActions } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { EventConfigModal } from 'products/customer_analytics/frontend/components/Insights/EventConfigModal'
import { SessionInsights } from 'products/customer_analytics/frontend/components/Insights/SessionInsights'

import { CustomerAnalyticsFilters } from './CustomerAnalyticsFilters'
import { ActiveUsersInsights } from './components/Insights/ActiveUsersInsights'
import { SignupInsights } from './components/Insights/SignupInsights'
import { eventConfigModalLogic } from './components/Insights/eventConfigModalLogic'
import { CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID } from './constants'
import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

export const scene: SceneExport = {
    component: CustomerAnalyticsScene,
    logic: customerAnalyticsSceneLogic,
}

export function CustomerAnalyticsScene({ tabId }: { tabId?: string }): JSX.Element {
    const { toggleModalOpen } = useActions(eventConfigModalLogic)

    if (!tabId) {
        throw new Error('CustomerAnalyticsScene was rendered with no tabId')
    }

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.CustomerAnalytics].name}
                    description={sceneConfigurations[Scene.CustomerAnalytics].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.CustomerAnalytics].iconType || 'default_icon_type',
                    }}
                    actions={
                        <LemonButton
                            icon={<IconGear />}
                            size="small"
                            type="secondary"
                            onClick={() => toggleModalOpen()}
                            tooltip="Configure customer analytics"
                            children="Configure"
                        />
                    }
                />
                <CustomerAnalyticsFilters />
                <div className="space-y-2">
                    <ActiveUsersInsights />
                    <SignupInsights />
                    <SessionInsights />
                    <EventConfigModal />
                </div>
            </SceneContent>
        </BindLogic>
    )
}
