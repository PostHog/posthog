import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { DataWarehouseTab, dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DashboardTab } from './scene/DashboardTab'
import { DataModelingTab } from './scene/DataModelingTab'
import { OverviewTab } from './scene/OverviewTab'

export const scene: SceneExport = {
    component: DataWarehouseScene,
    logic: dataWarehouseSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
}

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(dataWarehouseSceneLogic)
    const { searchParams } = useValues(router)

    if (!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]) {
        return <NotFound object="Data warehouse" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.DataOps].name}
                description={sceneConfigurations[Scene.DataOps].description}
                resourceType={{
                    type: sceneConfigurations[Scene.DataOps].iconType || 'default_icon_type',
                }}
            />
            <LemonTabs
                activeKey={activeTab}
                sceneInset
                tabs={[
                    {
                        key: DataWarehouseTab.OVERVIEW,
                        label: 'Overview',
                        content: <OverviewTab />,
                        link: urls.dataOps(),
                    },
                    {
                        key: DataWarehouseTab.DASHBOARD,
                        label: 'Dashboard',
                        content: <DashboardTab />,
                        link: combineUrl(urls.dataOps(), {
                            ...searchParams,
                            tab: DataWarehouseTab.DASHBOARD,
                        }).url,
                    },
                    ...(featureFlags[FEATURE_FLAGS.DATA_MODELING_TAB]
                        ? [
                              {
                                  key: DataWarehouseTab.MODELING,
                                  label: 'Modeling',
                                  content: <DataModelingTab />,
                                  link: combineUrl(urls.dataOps(), {
                                      ...searchParams,
                                      tab: DataWarehouseTab.MODELING,
                                  }).url,
                              },
                          ]
                        : []),
                ]}
            />
        </SceneContent>
    )
}
