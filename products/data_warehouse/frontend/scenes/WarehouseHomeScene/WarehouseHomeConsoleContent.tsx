import { useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import { WarehouseExplainer } from './WarehouseExplainer'
import { WarehouseHomeOverview } from './WarehouseHomeOverview'
import { warehouseHomeView } from './warehouseHomeView'

/**
 * Warehouse home with the managed warehouse console on. Using the console logic loads the warehouse status, so the
 * scene renders this only when the console is on and leaves the flag-off page free of that request.
 */
export function WarehouseHomeConsoleContent(): JSX.Element {
    const { consoleState } = useValues(warehouseConsoleLogic)
    const view = warehouseHomeView(consoleState)

    if (view === 'loading') {
        return <Skeleton className="h-48 w-full" />
    }
    return view === 'explainer' ? <WarehouseExplainer /> : <WarehouseHomeOverview />
}
