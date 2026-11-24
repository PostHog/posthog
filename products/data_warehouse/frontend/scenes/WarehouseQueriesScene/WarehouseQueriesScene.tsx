import { useValues } from 'kea'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { type WarehousePageTab, WarehousePageTabs } from '../WarehouseConsole/WarehousePageTabs'
import { WarehousePerformance } from './WarehousePerformance'
import { WarehouseQueryHistory } from './WarehouseQueryHistory'
import { WarehouseRunningQueries } from './WarehouseRunningQueries'

export const scene: SceneExport = {
    component: WarehouseQueriesScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

const TABS: WarehousePageTab[] = [
    { value: 'activity', label: 'Activity', 'data-attr': 'warehouse-queries-tab-activity' },
    { value: 'performance', label: 'Performance', 'data-attr': 'warehouse-queries-tab-performance' },
]

function WarehouseQueriesContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page="queries" />
    }
    return (
        <WarehousePageTabs tabs={TABS} page="queries">
            {(tab) =>
                tab === 'performance' ? (
                    <WarehousePerformance />
                ) : (
                    <>
                        <WarehouseRunningQueries />
                        <WarehouseQueryHistory />
                    </>
                )
            }
        </WarehousePageTabs>
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
