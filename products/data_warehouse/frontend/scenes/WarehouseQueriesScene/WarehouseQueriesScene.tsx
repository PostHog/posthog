import { useValues } from 'kea'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehouseQueryHistory } from './WarehouseQueryHistory'
import { WarehouseRunningQueries } from './WarehouseRunningQueries'

export const scene: SceneExport = {
    component: WarehouseQueriesScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

function WarehouseQueriesContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page="queries" />
    }
    return (
        <>
            <WarehouseRunningQueries />
            <WarehouseQueryHistory />
        </>
    )
}

export function WarehouseQueriesScene(): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WarehouseQueries].name}
                    description={sceneConfigurations[Scene.WarehouseQueries].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-queries flex flex-col gap-4">
                    <WarehouseQueriesContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
