import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { WarehouseSettingsContent } from './WarehouseSettingsContent'

export const scene: SceneExport = {
    component: WarehouseSettingsScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

export function WarehouseSettingsScene(): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WarehouseSettings].name}
                    description={sceneConfigurations[Scene.WarehouseSettings].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-settings flex flex-col gap-4">
                    <WarehouseSettingsContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
