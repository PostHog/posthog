import { EventsNode } from '~/queries/nodes'
import { useState } from 'react'
import { EventsTable } from 'scenes/events'
import { AnyPropertyFilter } from '~/types'

let uniqueNode = 0
export function EventsNodeQuery({ query }: { query: EventsNode }): JSX.Element {
    const [id] = useState(uniqueNode++)

    return (
        <EventsTable
            pageKey={`events-node-${id}`}
            fixedFilters={{ properties: query.properties as AnyPropertyFilter[] }}
            showEventFilter={false}
            showPropertyFilter={false}
            showAutoload={false}
            showCustomizeColumns={false}
            showExport={false}
        />
    )
}
