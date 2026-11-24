import { useValues } from 'kea'

import { warehouseConsoleLogic } from './warehouseConsoleLogic'

/** The half of `WarehouseConsoleReady` that mounts the console logic, which loads the warehouse status. */
export function WarehouseConsoleReadyInner({ children }: { children: React.ReactNode }): JSX.Element | null {
    const { consoleState } = useValues(warehouseConsoleLogic)

    return consoleState === 'ready' ? <>{children}</> : null
}
