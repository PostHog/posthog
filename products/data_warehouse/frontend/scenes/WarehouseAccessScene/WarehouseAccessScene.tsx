import { useValues } from 'kea'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehouseLoginCard } from './WarehouseLoginCard'
import { WarehouseLoginsSection } from './WarehouseLoginsSection'

export const scene: SceneExport = {
    component: WarehouseAccessScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

function WarehouseAccessContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page="access" />
    }
    return (
        <>
            <WarehouseLoginCard />
            <WarehouseLoginsSection />
        </>
    )
}

export function WarehouseAccessScene(): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WarehouseAccess].name}
                    description={sceneConfigurations[Scene.WarehouseAccess].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-access flex flex-col gap-4">
                    <WarehouseAccessContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
