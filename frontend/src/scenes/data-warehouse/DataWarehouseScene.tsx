import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DataWarehouseTab, dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { OverviewTab } from './scene/OverviewTab'
import { SourcesTab } from './scene/SourcesTab'
import { ViewsTab } from './scene/ViewsTab'

export const scene: SceneExport = { component: DataWarehouseScene, logic: dataWarehouseSceneLogic }

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(dataWarehouseSceneLogic)
    const { setActiveTab } = useActions(dataWarehouseSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]) {
        return <NotFound object="Data warehouse" />
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
                        <AppShortcut
                            name="NewDataWarehouseSource"
                            keybind={[keyBinds.new]}
                            intent="New source"
                            interaction="click"
                            scope={Scene.DataWarehouse}
                        >
                            <LemonButton
                                type="primary"
                                to={urls.dataWarehouseSourceNew()}
                                icon={<IconPlusSmall />}
                                size="small"
                                tooltip="New source"
                            >
                                New source
                            </LemonButton>
                        </AppShortcut>
                    </div>
                }
            />
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
                    {
                        key: DataWarehouseTab.VIEWS,
                        label: 'Views',
                        content: <ViewsTab />,
                    },
                ]}
            />
        </SceneContent>
    )
}
