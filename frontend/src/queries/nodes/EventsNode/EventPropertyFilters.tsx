import { EventsNode, EventsQuery, HogQLQuery } from '~/queries/schema'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { AnyPropertyFilter } from '~/types'
import { useState } from 'react'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isHogQLQuery } from '~/queries/utils'

interface EventPropertyFiltersProps {
    query: EventsNode | EventsQuery | HogQLQuery
    setQuery?: (query: EventsNode | EventsQuery | HogQLQuery) => void
}

let uniqueNode = 0
export function EventPropertyFilters({ query, setQuery }: EventPropertyFiltersProps): JSX.Element {
    const [id] = useState(() => uniqueNode++)

    const properties = isHogQLQuery(query) ? query.filters?.properties : query.properties
    const eventNames = isHogQLQuery(query) ? [] : query.event ? [query.event] : []

    return !properties || Array.isArray(properties) ? (
        <PropertyFilters
            propertyFilters={properties || []}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.Elements,
                TaxonomicFilterGroupType.HogQLExpression,
            ]}
            onChange={(value: AnyPropertyFilter[]) => {
                if (isHogQLQuery(query)) {
                    setQuery?.({ ...query, filters: { ...(query.filters ?? {}), properties: value } })
                } else {
                    setQuery?.({ ...query, properties: value })
                }
            }}
            pageKey={`EventPropertyFilters.${id}`}
            eventNames={eventNames}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
