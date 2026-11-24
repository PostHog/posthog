import { useActions, useValues } from 'kea'

import { urls } from 'scenes/urls'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseSectionLink } from '../WarehouseConsole/WarehouseSectionLink'
import { WarehousePipelineDatasetRow } from './WarehousePipelineDatasetRow'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

/** Events and persons, the data PostHog ingests continuously, and how much of it the warehouse holds. */
export function WarehousePipelineEventData(): JSX.Element | null {
    const { managedWarehouseDataStatus, ingestedEvent } = useValues(warehousePipelineHealthLogic)
    const { linkClicked } = useActions(warehousePipelineHealthLogic)

    if (!managedWarehouseDataStatus) {
        return null
    }
    return (
        <WarehouseSection
            title="PostHog data"
            description={
                ingestedEvent
                    ? 'Events and persons arrive in PostHog continuously. This shows how much has been copied into your warehouse.'
                    : 'No events have been ingested into PostHog yet, so there is nothing to copy into your warehouse.'
            }
            flush
            data-attr="warehouse-pipeline-health-events"
            controls={
                <>
                    <WarehouseSectionLink
                        to={urls.eventFiltering()}
                        onClick={() => linkClicked('event_filtering')}
                        data-attr="warehouse-pipeline-health-event-filtering"
                    >
                        Event ingestion filtering
                    </WarehouseSectionLink>
                    <WarehouseSectionLink
                        to={urls.ingestionWarnings()}
                        onClick={() => linkClicked('ingestion_warnings')}
                        data-attr="warehouse-pipeline-health-ingestion-warnings"
                    >
                        Ingestion warnings
                    </WarehouseSectionLink>
                </>
            }
        >
            <div className="divide-y">
                <WarehousePipelineDatasetRow label="Events" dataset={managedWarehouseDataStatus.events} />
                <WarehousePipelineDatasetRow label="Persons" dataset={managedWarehouseDataStatus.persons} />
            </div>
        </WarehouseSection>
    )
}
