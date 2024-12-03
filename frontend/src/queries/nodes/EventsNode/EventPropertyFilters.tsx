import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'

import { EventsNode, EventsQuery, HogQLQuery, SessionAttributionExplorerQuery } from '~/queries/schema'
import { isHogQLQuery, isSessionAttributionExplorerQuery } from '~/queries/utils'
import { AnyPropertyFilter } from '~/types'

interface EventPropertyFiltersProps<Q extends EventsNode | EventsQuery | HogQLQuery | SessionAttributionExplorerQuery> {
    query: Q
    setQuery?: (query: Q) => void
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
}

let uniqueNode = 0
export function EventPropertyFilters<
    Q extends EventsNode | EventsQuery | HogQLQuery | SessionAttributionExplorerQuery
>({ query, setQuery, taxonomicGroupTypes }: EventPropertyFiltersProps<Q>): JSX.Element {
    const [id] = useState(() => uniqueNode++)
    const properties =
        isHogQLQuery(query) || isSessionAttributionExplorerQuery(query) ? query.filters?.properties : query.properties
    const eventNames =
        isHogQLQuery(query) || isSessionAttributionExplorerQuery(query) ? [] : query.event ? [query.event] : []

    return !properties || Array.isArray(properties) ? (
        <PropertyFilters
            propertyFilters={properties || []}
            taxonomicGroupTypes={
                taxonomicGroupTypes || [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]
            }
            onChange={(value: AnyPropertyFilter[]) => {
                if (isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)) {
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
