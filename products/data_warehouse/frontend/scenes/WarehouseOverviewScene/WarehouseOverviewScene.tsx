import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { WarehouseOverviewContent } from './WarehouseOverviewContent'

export const scene: SceneExport = {
    component: WarehouseOverviewScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

export function WarehouseOverviewScene(): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WarehouseOverview].name}
                    description={sceneConfigurations[Scene.WarehouseOverview].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-overview flex flex-col gap-6">
                    <WarehouseOverviewContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
