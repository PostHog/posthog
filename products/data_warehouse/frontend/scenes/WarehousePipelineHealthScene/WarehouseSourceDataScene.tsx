import { Scene, SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { WarehousePipelinePage } from './WarehousePipelinePage'
import { WarehousePipelineSources } from './WarehousePipelineSources'
import { WarehousePipelineSourceTables } from './WarehousePipelineSourceTables'

export const scene: SceneExport = {
    component: WarehouseSourceDataScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

/** Whether each batch that a source syncs has landed in the warehouse. */
export function WarehouseSourceDataScene(): JSX.Element {
    return (
        <WarehousePipelinePage scene={Scene.WarehouseSourceData} page="source_data">
            <WarehousePipelineSources />
            <WarehousePipelineSourceTables />
        </WarehousePipelinePage>
    )
}
