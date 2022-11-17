import { EventsTableNode } from '~/queries/nodes'
import { useState } from 'react'
import { EventsTable } from 'scenes/events'
import { AnyPropertyFilter } from '~/types'

interface EventsTableQueryProps {
    query: EventsTableNode
    setQuery?: (node: EventsTableNode) => void
}

let uniqueNode = 0
export function EventsTableQuery({ query }: EventsTableQueryProps): JSX.Element {
    const [id] = useState(uniqueNode++)

    return (
        <EventsTable
            pageKey={`events-node-${id}`}
            fixedFilters={{ properties: query.events.properties as AnyPropertyFilter[] }}
            showEventFilter={false}
            showPropertyFilter={false}
            showAutoload={false}
            showCustomizeColumns={false}
            showExport={false}
        />
    )
}
