import { WarehouseConsoleReady } from '../WarehouseConsole/WarehouseConsoleReady'
import { WarehouseUsageStrip } from './WarehouseUsageStrip'

/** The headline numbers of the managed warehouse. It mounts only with the console flag on and the warehouse ready. */
export function WarehouseHomeSummary(): JSX.Element {
    return (
        <WarehouseConsoleReady>
            <section aria-label="Warehouse summary">
                <WarehouseUsageStrip />
            </section>
        </WarehouseConsoleReady>
    )
}
