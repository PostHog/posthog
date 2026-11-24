import { useMountedLogic } from 'kea'

import { warehouseShellStatusLogic } from './warehouseShellStatusLogic'

/** Renders nothing. Mounting it makes the navigation shell learn whether a managed warehouse exists. */
export function WarehouseShellStatusReporter(): null {
    useMountedLogic(warehouseShellStatusLogic)
    return null
}
