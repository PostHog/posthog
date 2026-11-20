import { Heading } from '@posthog/quill'

import { WarehouseConsoleReady } from '../WarehouseConsole/WarehouseConsoleReady'
import { WarehouseLiveWorkload } from './WarehouseLiveWorkload'
import { WarehouseRecommendations } from './WarehouseRecommendations'
import { WarehouseTopConsumers } from './WarehouseTopConsumers'
import { WarehouseUsageStrip } from './WarehouseUsageStrip'

/** The managed warehouse console summary. It mounts only with the console flag on and the warehouse ready. */
export function WarehouseConsoleOverview(): JSX.Element {
    return (
        <WarehouseConsoleReady>
            <section aria-labelledby="warehouse-usage-overview" className="flex flex-col gap-2">
                <Heading render={<h2 id="warehouse-usage-overview" />} size="base" className="m-0">
                    Usage
                </Heading>
                <WarehouseUsageStrip />
                <div className="grid gap-3 @3xl/warehouse-home:grid-cols-2">
                    <WarehouseLiveWorkload />
                    <WarehouseTopConsumers />
                </div>
                <WarehouseRecommendations />
            </section>
        </WarehouseConsoleReady>
    )
}
