import { Heading } from '@posthog/quill'

import { WarehouseConsoleReady } from '../WarehouseConsole/WarehouseConsoleReady'
import { WarehouseUsageStrip } from './WarehouseUsageStrip'

/** The headline numbers of the managed warehouse. It mounts only with the console flag on and the warehouse ready. */
export function WarehouseHomeSummary(): JSX.Element {
    return (
        <WarehouseConsoleReady>
            <section aria-labelledby="warehouse-summary" className="flex flex-col gap-2">
                <Heading render={<h2 id="warehouse-summary" />} size="base" className="m-0">
                    Warehouse
                </Heading>
                <WarehouseUsageStrip />
            </section>
        </WarehouseConsoleReady>
    )
}
