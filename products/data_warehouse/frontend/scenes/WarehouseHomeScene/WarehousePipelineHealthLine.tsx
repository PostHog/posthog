import { useValues } from 'kea'
import posthog from 'posthog-js'

import { Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { managedWarehouseDataStatusLogic } from '../DataOpsScene/tabs/managedWarehouseDataStatusLogic'
import { WarehouseConsoleReady } from '../WarehouseConsole/WarehouseConsoleReady'
import { WarehouseSectionLink } from '../WarehouseConsole/WarehouseSectionLink'
import { landingSummary, landingTotals } from '../WarehousePipelineHealthScene/pipelineHealthStats'

function WarehousePipelineHealthLineBody(): JSX.Element | null {
    const { managedWarehouseDataStatus } = useValues(managedWarehouseDataStatusLogic)

    // Nothing shows while the status loads or when it failed, so the line never reports a state it does not know.
    if (!managedWarehouseDataStatus) {
        return null
    }
    const { text } = landingSummary(landingTotals(managedWarehouseDataStatus))
    return (
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <Text size="xs" variant="muted" data-attr="warehouse-home-pipeline-health-summary" render={<span />}>
                {text}
            </Text>
            <WarehouseSectionLink
                to={urls.warehousePipelineHealth()}
                onClick={() => {
                    posthog.capture('warehouse overview link clicked', { target: 'pipeline_health' })
                }}
                data-attr="warehouse-home-pipeline-health-link"
            >
                Pipeline health
            </WarehouseSectionLink>
        </div>
    )
}

/** One muted line under the Pipelines heading on how much has landed in the warehouse, with a link to Pipeline health. */
export function WarehousePipelineHealthLine(): JSX.Element {
    return (
        <WarehouseConsoleReady>
            <WarehousePipelineHealthLineBody />
        </WarehouseConsoleReady>
    )
}
