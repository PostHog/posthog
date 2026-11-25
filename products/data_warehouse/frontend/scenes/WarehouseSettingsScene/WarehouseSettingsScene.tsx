import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { WarehouseSettingsContent } from './WarehouseSettingsContent'
import { WarehouseSettingsTitle } from './WarehouseSettingsTitle'

export const scene: SceneExport = {
    component: WarehouseSettingsScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

export function WarehouseSettingsScene(): JSX.Element {
    return (
        <WarehouseConsoleGate kind="setup">
            <SceneContent>
                <WarehouseSettingsTitle />
                <div data-quill className="@container/warehouse-settings flex flex-col gap-4">
                    <WarehouseSettingsContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
