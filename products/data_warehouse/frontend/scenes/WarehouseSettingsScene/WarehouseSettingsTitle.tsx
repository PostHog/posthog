import { useValues } from 'kea'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'

/** The page title: "Setup" until a warehouse exists, since there is nothing to change settings on before then. */
export function WarehouseSettingsTitle(): JSX.Element {
    const { consoleState, warehouseStatus } = useValues(warehouseConsoleLogic)
    const settingUp = consoleState === 'no_warehouse' || warehouseStatus?.state === 'failed'

    return (
        <SceneTitleSection
            name={settingUp ? 'Setup' : sceneConfigurations[Scene.WarehouseSettings].name}
            description={
                settingUp
                    ? "Create your organization's warehouse and add this project to it."
                    : sceneConfigurations[Scene.WarehouseSettings].description
            }
            resourceType={{ type: 'data_warehouse' }}
        />
    )
}
