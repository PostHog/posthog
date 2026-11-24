import { useValues } from 'kea'

import { Heading } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { WarehouseGettingStarted } from './WarehouseGettingStarted'
import { WarehouseHealth } from './WarehouseHealth'
import { WarehouseHomeSummary } from './WarehouseHomeSummary'
import { WarehousePipelineHealthLine } from './WarehousePipelineHealthLine'
import { WarehousePipelineStats } from './WarehousePipelineStats'
import { WarehousePipelinesWindow } from './WarehousePipelinesWindow'
import { WarehouseRecentRuns } from './WarehouseRecentRuns'

/** The usual content of Warehouse home: getting started, the summary and the pipelines overview. */
export function WarehouseHomeOverview(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const consoleOn = !!featureFlags[FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]

    return (
        <>
            <WarehouseGettingStarted />
            <WarehouseHomeSummary />
            <section aria-labelledby="warehouse-overview" className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading render={<h2 id="warehouse-overview" />} size="base" className="m-0">
                        {consoleOn ? 'Pipelines' : 'Overview'}
                    </Heading>
                    <WarehousePipelinesWindow />
                </div>
                <WarehousePipelineHealthLine />
                <WarehousePipelineStats />
                <div className="grid gap-3 @7xl/warehouse-home:grid-cols-2">
                    <WarehouseHealth />
                    <WarehouseRecentRuns />
                </div>
            </section>
        </>
    )
}
