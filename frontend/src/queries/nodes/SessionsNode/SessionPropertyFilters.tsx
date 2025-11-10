import { useState } from 'react'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { SessionsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

interface SessionPropertyFiltersProps {
    query: SessionsQuery
    setQuery?: (query: SessionsQuery) => void
}

let uniqueNode = 0
export function SessionPropertyFilters({ query, setQuery }: SessionPropertyFiltersProps): JSX.Element {
    const [id] = useState(() => uniqueNode++)

    // Determine which properties we're currently filtering on
    const hasEventFilter = !!(query.event || query.actionId)

    // Combine session properties and event properties for display
    const allProperties = [...(query.properties || []), ...(query.eventProperties || [])]

    // Determine which taxonomic groups to show
    const taxonomicGroupTypes = hasEventFilter
        ? [
              // Session properties
              TaxonomicFilterGroupType.SessionProperties,
              // Event properties (only when event is selected)
              TaxonomicFilterGroupType.EventProperties,
              TaxonomicFilterGroupType.PersonProperties,
              TaxonomicFilterGroupType.EventFeatureFlags,
              TaxonomicFilterGroupType.Cohorts,
              TaxonomicFilterGroupType.HogQLExpression,
          ]
        : [
              // Only session properties when no event selected
              TaxonomicFilterGroupType.SessionProperties,
              TaxonomicFilterGroupType.HogQLExpression,
          ]

    return !query.properties || Array.isArray(query.properties) ? (
        <PropertyFilters
            propertyFilters={allProperties}
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={(value: AnyPropertyFilter[]) => {
                if (!hasEventFilter) {
                    // No event filter: all properties are session properties
                    setQuery?.({ ...query, properties: value, eventProperties: [] })
                } else {
                    // Event filter active: split properties by their type field
                    const sessionProps = value.filter((prop) => 'type' in prop && prop.type === 'session')
                    const eventProps = value.filter(
                        (prop) => 'type' in prop && (prop.type === 'event' || prop.type === 'person')
                    )
                    setQuery?.({
                        ...query,
                        properties: sessionProps,
                        eventProperties: eventProps,
                    })
                }
            }}
            pageKey={`SessionPropertyFilters.${id}`}
            eventNames={query.event ? [query.event] : []}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
