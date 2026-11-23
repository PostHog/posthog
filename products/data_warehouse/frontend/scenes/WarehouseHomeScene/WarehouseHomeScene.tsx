import { useValues } from 'kea'

import { Heading } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseGettingStarted } from './WarehouseGettingStarted'
import { WarehouseHealth } from './WarehouseHealth'
import { WarehouseHomeSummary } from './WarehouseHomeSummary'
import { WarehousePipelineStats } from './WarehousePipelineStats'
import { WarehousePipelinesWindow } from './WarehousePipelinesWindow'
import { WarehouseRecentRuns } from './WarehouseRecentRuns'

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
                <WarehouseGettingStarted />
                <WarehouseHomeSummary />
                <section aria-labelledby="warehouse-overview" className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Heading render={<h2 id="warehouse-overview" />} size="base" className="m-0">
                            {consoleOn ? 'Pipelines' : 'Overview'}
                        </Heading>
                        <WarehousePipelinesWindow />
                    </div>
                    <WarehousePipelineStats />
                    <div className="grid gap-3 @7xl/warehouse-home:grid-cols-2">
                        <WarehouseHealth />
                        <WarehouseRecentRuns />
                    </div>
                </section>
            </div>
        </SceneContent>
    )
}
