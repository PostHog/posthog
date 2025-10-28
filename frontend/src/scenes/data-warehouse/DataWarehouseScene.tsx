import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DataWarehouseTab, dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { OverviewTab } from './scene/OverviewTab'
import { SourcesTab } from './scene/SourcesTab'

export const scene: SceneExport = { component: DataWarehouseScene, logic: dataWarehouseSceneLogic }

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(dataWarehouseSceneLogic)
    const { setActiveTab } = useActions(dataWarehouseSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]) {
        return <NotFound object="Data Warehouse" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.DataWarehouse].name}
                description={sceneConfigurations[Scene.DataWarehouse].description}
                resourceType={{
                    type: sceneConfigurations[Scene.DataWarehouse].iconType || 'default_icon_type',
                }}
                actions={
                    <div className="flex gap-2">
                        <LemonButton type="secondary" to={urls.sqlEditor()} size="small">
                            Create view
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            to={urls.dataWarehouseSourceNew()}
                            icon={<IconPlusSmall />}
                            size="small"
                        >
                            New source
                        </LemonButton>
                    </div>
                }
            />
            <SceneDivider />
            <LemonTabs
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                sceneInset
                tabs={[
                    {
                        key: DataWarehouseTab.OVERVIEW,
                        label: 'Overview',
                        content: <OverviewTab />,
                    },
                    {
                        key: DataWarehouseTab.SOURCES,
                        label: 'Sources',
                        content: <SourcesTab />,
                    },
                ]}
            />
        </SceneContent>
    )
}
