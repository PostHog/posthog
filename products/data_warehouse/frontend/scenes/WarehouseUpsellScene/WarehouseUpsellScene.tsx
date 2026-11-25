import { useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehouseExplainer } from './WarehouseExplainer'

export const scene: SceneExport = {
    component: WarehouseUpsellScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

function WarehouseUpsellContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)

    if (consoleState === 'no_warehouse') {
        return <WarehouseExplainer />
    }
    // With a warehouse the redirect to Overview is under way. An error shows its retry.
    return consoleState === 'error' ? <WarehouseConsoleState page="upsell" /> : <Skeleton className="h-48 w-full" />
}

export function WarehouseUpsellScene(): JSX.Element {
    return (
        <WarehouseConsoleGate kind="upsell">
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.Warehouse].name}
                    description={sceneConfigurations[Scene.Warehouse].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-upsell flex flex-col gap-6">
                    <WarehouseUpsellContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
