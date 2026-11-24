import { useValues } from 'kea'

import type { ManagedWarehouseDatasetStatusApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { managedWarehouseDataStatusLogic } from '../DataOpsScene/tabs/managedWarehouseDataStatusLogic'
import { formatCount } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseStatStrip } from '../WarehouseConsole/WarehouseStatStrip'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'

function datasetTile(label: string, dataAttr: string, status: ManagedWarehouseDatasetStatusApi): JSX.Element {
    const total = status.total_partitions
    return (
        <WarehouseStatTile
            label={label}
            badge={<WarehouseStatusBadge status={status.readiness_state} />}
            value={
                total !== null && total > 0
                    ? `${formatCount(status.completed_partitions)} of ${formatCount(total)} partitions`
                    : 'Calculating partitions'
            }
            detail={status.detail}
            meter={total !== null && total > 0 ? { used: status.completed_partitions, limit: total } : undefined}
            data-attr={dataAttr}
        />
    )
}

/** The Events and Persons backfill status. */
export function WarehouseReadinessDatasets(): JSX.Element | null {
    const { managedWarehouseDataStatus } = useValues(managedWarehouseDataStatusLogic)
    if (!managedWarehouseDataStatus) {
        return null
    }
    return (
        <WarehouseStatStrip maxColumns={2}>
            {datasetTile('Events backfill', 'warehouse-readiness-events', managedWarehouseDataStatus.events)}
            {datasetTile('Persons backfill', 'warehouse-readiness-persons', managedWarehouseDataStatus.persons)}
        </WarehouseStatStrip>
    )
}
