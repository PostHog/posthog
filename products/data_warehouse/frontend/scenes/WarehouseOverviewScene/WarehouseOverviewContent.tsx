import { useValues } from 'kea'

import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseConsoleState } from '../WarehouseConsole/WarehouseConsoleState'
import { WarehouseGettingStarted } from './WarehouseGettingStarted'
import { WarehouseOverviewSummary } from './WarehouseOverviewSummary'
import { WarehousePipelinesSection } from './WarehousePipelinesSection'

/** The overview sections mount only once the warehouse is ready, so a warehouse that is not ready makes none of their requests. */
export function WarehouseOverviewContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)

    if (consoleState !== 'ready') {
        return <WarehouseConsoleState page="overview" />
    }
    return (
        <>
            <WarehouseGettingStarted />
            <WarehouseOverviewSummary />
            <WarehousePipelinesSection />
        </>
    )
}
