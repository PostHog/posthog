import { Heading } from '@posthog/quill'

import { WarehouseUsageStrip } from './WarehouseUsageStrip'

/** The headline numbers of the managed warehouse. */
export function WarehouseOverviewSummary(): JSX.Element {
    return (
        <section aria-labelledby="warehouse-summary" className="flex flex-col gap-2">
            <Heading render={<h2 id="warehouse-summary" />} size="base" className="m-0">
                Warehouse
            </Heading>
            <WarehouseUsageStrip />
        </section>
    )
}
