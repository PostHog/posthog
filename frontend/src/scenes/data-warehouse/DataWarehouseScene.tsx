import { useActions, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { DataWarehouseTab, dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataModelingTab } from './scene/DataModelingTab'
import { OverviewTab } from './scene/OverviewTab'
import { SettingsTab } from './scene/SettingsTab'

export const scene: SceneExport = {
    component: DataWarehouseScene,
    logic: dataWarehouseSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
}

const TAB_LABELS: Record<DataWarehouseTab, string> = {
    [DataWarehouseTab.OVERVIEW]: 'Overview',
    [DataWarehouseTab.SETTINGS]: 'Settings',
    [DataWarehouseTab.MODELING]: 'Modeling',
}

function tabContent(tab: DataWarehouseTab): JSX.Element {
    switch (tab) {
        case DataWarehouseTab.OVERVIEW:
            return <OverviewTab />
        case DataWarehouseTab.SETTINGS:
            return <SettingsTab />
        case DataWarehouseTab.MODELING:
            return <DataModelingTab />
    }
}

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { availableTabs, activeTab, warehouseStatusResolved } = useValues(dataWarehouseSceneLogic)
    const { setActiveTab } = useActions(dataWarehouseSceneLogic)

    // Nothing to show without the scene flag, or when no tab's feature flag is enabled.
    if (!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE] || !activeTab) {
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
            {/* Which tabs exist depends on whether a warehouse is ready, so wait for that rather
                than rendering the setup form and then swapping it for tabs a moment later. */}
            {!warehouseStatusResolved ? (
                <div className="mt-4 flex items-center gap-2 text-muted">
                    <Spinner />
                    <span>Loading warehouse...</span>
                </div>
            ) : availableTabs.length > 1 ? (
                <LemonTabs
                    activeKey={activeTab}
                    sceneInset
                    onChange={setActiveTab}
                    tabs={availableTabs.map((tab) => ({
                        key: tab,
                        label: TAB_LABELS[tab],
                        content: tabContent(tab),
                    }))}
                />
            ) : (
                tabContent(activeTab)
            )}
        </SceneContent>
    )
}
