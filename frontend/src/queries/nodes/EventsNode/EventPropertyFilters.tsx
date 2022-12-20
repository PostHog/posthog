import { EventsNode, EventsQuery } from '~/queries/schema'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { AnyPropertyFilter } from '~/types'
import { useState } from 'react'

interface EventPropertyFiltersProps {
    query: EventsNode | EventsQuery
    setQuery?: (node: EventsNode | EventsQuery) => void
}

let uniqueNode = 0
export function EventPropertyFilters({ query, setQuery }: EventPropertyFiltersProps): JSX.Element {
    const [id] = useState(() => uniqueNode++)
    return !query.properties || Array.isArray(query.properties) ? (
        <PropertyFilters
            propertyFilters={query.properties || []}
            onChange={(value: AnyPropertyFilter[]) => setQuery?.({ ...query, properties: value })}
            pageKey={`EventPropertyFilters.${id}`}
            style={{ marginBottom: 0, marginTop: 0 }}
            eventNames={query.event ? [query.event] : []}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
