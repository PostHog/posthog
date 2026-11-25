import { Heading } from '@posthog/quill'

import { WarehouseHealth } from './WarehouseHealth'
import { WarehousePipelineHealthLine } from './WarehousePipelineHealthLine'
import { WarehousePipelineStats } from './WarehousePipelineStats'
import { WarehousePipelinesWindow } from './WarehousePipelinesWindow'
import { WarehouseRecentRuns } from './WarehouseRecentRuns'

/** How the pipelines that feed the warehouse are doing: run statistics, what needs attention and the latest runs. */
export function WarehousePipelinesSection(): JSX.Element {
    return (
        <section aria-labelledby="warehouse-pipelines" className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Heading render={<h2 id="warehouse-pipelines" />} size="base" className="m-0">
                    Pipelines
                </Heading>
                <WarehousePipelinesWindow />
            </div>
            <WarehousePipelineHealthLine />
            <WarehousePipelineStats />
            <div className="grid gap-3 @7xl/warehouse-overview:grid-cols-2">
                <WarehouseHealth />
                <WarehouseRecentRuns />
            </div>
        </section>
    )
}
