import type { WarehouseConsoleState } from '../WarehouseConsole/warehouseConsoleLogic'

export type WarehouseHomeView = 'overview' | 'loading' | 'explainer'

/**
 * What Warehouse home shows with the console on. The explainer replaces the overview only when the status says there
 * is no warehouse. While the status loads the page shows a placeholder, and a failed load keeps the overview.
 */
export function warehouseHomeView(consoleState: WarehouseConsoleState): WarehouseHomeView {
    if (consoleState === 'loading') {
        return 'loading'
    }
    return consoleState === 'no_warehouse' ? 'explainer' : 'overview'
}
