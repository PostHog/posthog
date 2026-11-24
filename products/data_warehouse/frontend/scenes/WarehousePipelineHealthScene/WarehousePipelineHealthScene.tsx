import { useValues } from 'kea'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehousePipelineHealthContent } from './WarehousePipelineHealthContent'

export const scene: SceneExport = {
    component: WarehousePipelineHealthScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

function WarehousePipelineHealthBody(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page="pipeline_health" />
    }
    return <WarehousePipelineHealthContent />
}

export function WarehousePipelineHealthScene(): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WarehousePipelineHealth].name}
                    description={sceneConfigurations[Scene.WarehousePipelineHealth].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-pipeline-health flex flex-col gap-4">
                    <WarehousePipelineHealthBody />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
