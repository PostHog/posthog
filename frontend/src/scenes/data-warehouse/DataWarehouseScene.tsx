import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { SettingsTab } from './scene/SettingsTab'

export const scene: SceneExport = {
    component: DataWarehouseScene,
    logic: dataWarehouseSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
}

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

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
            <SettingsTab />
        </SceneContent>
    )
}
