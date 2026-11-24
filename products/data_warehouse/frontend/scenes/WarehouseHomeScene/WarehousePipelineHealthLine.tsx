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
            <div className="flex flex-wrap items-center gap-x-1">
                <WarehouseSectionLink
                    to={urls.warehousePostHogData()}
                    onClick={() => {
                        posthog.capture('warehouse overview link clicked', { target: 'posthog_data' })
                    }}
                    data-attr="warehouse-home-posthog-data-link"
                >
                    PostHog data
                </WarehouseSectionLink>
                <WarehouseSectionLink
                    to={urls.warehouseSourceData()}
                    onClick={() => {
                        posthog.capture('warehouse overview link clicked', { target: 'source_data' })
                    }}
                    data-attr="warehouse-home-source-data-link"
                >
                    Source data
                </WarehouseSectionLink>
            </div>
        </div>
    )
}

/** One muted line under the Pipelines heading on how much has landed in the warehouse, with links to the PostHog data and Source data pages. */
export function WarehousePipelineHealthLine(): JSX.Element {
    return (
        <WarehouseConsoleReady>
            <WarehousePipelineHealthLineBody />
        </WarehouseConsoleReady>
    )
}
