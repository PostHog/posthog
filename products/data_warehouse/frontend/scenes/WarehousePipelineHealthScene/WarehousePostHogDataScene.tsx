import { Scene, SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { WarehousePipelineEventData } from './WarehousePipelineEventData'
import { WarehousePipelinePage } from './WarehousePipelinePage'

export const scene: SceneExport = {
    component: WarehousePostHogDataScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

/** How much of the data PostHog ingests continuously, events and persons, has landed in the warehouse. */
export function WarehousePostHogDataScene(): JSX.Element {
    return (
        <WarehousePipelinePage scene={Scene.WarehousePostHogData} page="posthog_data">
            <WarehousePipelineEventData />
        </WarehousePipelinePage>
    )
}
