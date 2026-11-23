import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { formatBytes, formatCount } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseConsoleGate } from '../WarehouseConsole/WarehouseConsoleGate'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseStatStrip } from '../WarehouseConsole/WarehouseStatStrip'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { warehouseStorageLogic } from './warehouseStorageLogic'
import { WarehouseStorageMaintenance } from './WarehouseStorageMaintenance'
import { WarehouseStorageTables } from './WarehouseStorageTables'

export const scene: SceneExport = {
    component: WarehouseStorageScene,
    productKey: ProductKey.DATA_WAREHOUSE,
}

function WarehouseStorageContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)
    const { storage, storageLoading, storageFailed, tableRows, totalRows } = useValues(warehouseStorageLogic)
    const { retryStorage } = useActions(warehouseStorageLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page="storage" />
    }
    if (storageFailed) {
        return (
            <WarehouseResourceError
                title="Couldn't load storage"
                onRetry={retryStorage}
                data-attr="warehouse-storage-retry"
            />
        )
    }
    if (!storage) {
        return storageLoading ? <Skeleton className="h-64 w-full" /> : <></>
    }
    return (
        <>
            <WarehouseStatStrip>
                <WarehouseStatTile
                    label="Total stored"
                    value={formatBytes(storage.total_bytes)}
                    detail="Includes time-travel history"
                    data-attr="warehouse-storage-tile-total"
                />
                <WarehouseStatTile
                    label="Tables"
                    value={formatCount(tableRows.length)}
                    data-attr="warehouse-storage-tile-tables"
                />
                <WarehouseStatTile
                    label="Rows"
                    value={formatCount(totalRows)}
                    data-attr="warehouse-storage-tile-rows"
                />
                <WarehouseStatTile
                    label="Files pending deletion"
                    value={formatCount(storage.pending_deletion_files)}
                    data-attr="warehouse-storage-tile-pending"
                />
            </WarehouseStatStrip>
            <WarehouseStorageTables />
            <WarehouseStorageMaintenance />
        </>
    )
}

export function WarehouseStorageScene(): JSX.Element {
    return (
        <WarehouseConsoleGate>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WarehouseStorage].name}
                    description={sceneConfigurations[Scene.WarehouseStorage].description}
                    resourceType={{ type: 'data_warehouse' }}
                />
                <div data-quill className="@container/warehouse-storage flex flex-col gap-4">
                    <WarehouseStorageContent />
                </div>
            </SceneContent>
        </WarehouseConsoleGate>
    )
}
