import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseHomeConsoleContent } from './WarehouseHomeConsoleContent'
import { WarehouseHomeOverview } from './WarehouseHomeOverview'

export const scene: SceneExport = {
    component: WarehouseHomeScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

export function WarehouseHomeScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    // The page belongs to the warehouse area of the rail navigation, so it does not exist without both flags.
    if (!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] || !featureFlags[FEATURE_FLAGS.TODAY_RAIL_WAREHOUSE]) {
        return <NotFound object="page" />
    }

    const consoleOn = !!featureFlags[FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.WarehouseHome].name}
                description={sceneConfigurations[Scene.WarehouseHome].description}
                resourceType={{ type: 'data_warehouse' }}
            />
            <div data-quill className="@container/warehouse-home flex flex-col gap-6">
                {consoleOn ? <WarehouseHomeConsoleContent /> : <WarehouseHomeOverview />}
            </div>
        </SceneContent>
    )
}
