import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useCallback, useState } from 'react'

import { EventsNode, EventsQuery, HogQLQuery, LogsQuery } from '~/queries/schema'
import { isHogQLQuery, isLogsQuery } from '~/queries/utils'
import { AnyPropertyFilter } from '~/types'

interface EventPropertyFiltersProps<Q extends EventsNode | EventsQuery | HogQLQuery | LogsQuery> {
    query: Q
    setQuery?: (query: Q) => void
    filterGroupTypes?: TaxonomicFilterGroupType[]
}

let uniqueNode = 0
export function EventPropertyFilters<Q extends EventsNode | EventsQuery | HogQLQuery | LogsQuery>({
    query,
    setQuery,
    filterGroupTypes,
}: EventPropertyFiltersProps<Q>): JSX.Element {
    const [id] = useState(() => uniqueNode++)

    const properties = isHogQLQuery(query) ? query.filters?.properties : query.properties

    const getEventNames = useCallback(() => {
        if (isHogQLQuery(query)) {
            return []
        } else if (isLogsQuery(query)) {
            return ['$log']
        }

        return query.event ? [query.event] : []
    }, [query])

    const eventNames = getEventNames()

    return !properties || Array.isArray(properties) ? (
        <PropertyFilters
            propertyFilters={properties || []}
            taxonomicGroupTypes={
                filterGroupTypes ?? [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]
            }
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
