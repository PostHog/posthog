import { LemonCheckbox } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ErrorEventType } from 'lib/components/Errors/types'
import { getExceptionAttributes } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { useErrorTagRenderer } from 'scenes/error-tracking/hooks/use-error-tag-renderer'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { DataTable, DataTableColumn } from '../DataTable/DataTable'
import { ExceptionAttributesPreview } from '../ExceptionAttributesPreview'
import { eventsQueryLogic } from './eventsQueryLogic'
import { eventsSourceLogic } from './eventsSourceLogic'

export interface EventsTableProps {
    issueId: string
    selectedEvent: ErrorEventType | null
    onEventSelect: (event: ErrorEventType | null) => void
}

export function EventsTable({ issueId, selectedEvent, onEventSelect }: EventsTableProps): JSX.Element {
    const { query, queryKey } = useValues(eventsQueryLogic({ issueId }))
    const tagRenderer = useErrorTagRenderer()
    const dataSource = eventsSourceLogic({ queryKey, query })

    function isEventSelected(record: ErrorEventType): boolean {
        return selectedEvent ? selectedEvent.uuid === record.uuid : false
    }

    function toggleSelectedEvent(record: ErrorEventType): void {
        return isEventSelected(record) ? onEventSelect(null) : onEventSelect(record)
    }

    function renderUUID(record: ErrorEventType): JSX.Element {
        // Click event is catch at the row level
        return <LemonCheckbox checked={isEventSelected(record)} />
    }

    function renderPerson(record: ErrorEventType): JSX.Element {
        return <PersonDisplay person={record.person} withIcon noPopover noLink />
    }

    function renderAttributes(record: ErrorEventType): JSX.Element {
        return (
            <div className="flex justify-end gap-1">
                {tagRenderer(record)}
                <ExceptionAttributesPreview attributes={getExceptionAttributes(record.properties)} />
            </div>
        )
    }

    function renderTime(record: ErrorEventType): JSX.Element {
        return <TZLabel time={record.timestamp} />
    }

    return (
        <DataTable<ErrorEventType> dataSource={dataSource} embedded onRowClick={toggleSelectedEvent}>
            <DataTableColumn<ErrorEventType> width="40px" cellRenderer={renderUUID} />
            <DataTableColumn<ErrorEventType> title="Person" cellRenderer={renderPerson} />
            <DataTableColumn<ErrorEventType> title="Time" cellRenderer={renderTime} />
            <DataTableColumn<ErrorEventType> align="right" cellRenderer={renderAttributes} />
        </DataTable>
    )
}
