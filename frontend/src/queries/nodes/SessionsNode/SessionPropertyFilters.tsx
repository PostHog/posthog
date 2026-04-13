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

    const allProperties = [...(query.properties || []), ...(query.eventProperties || [])]

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.SessionProperties,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    return !query.properties || Array.isArray(query.properties) ? (
        <PropertyFilters
            propertyFilters={allProperties}
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={(value: AnyPropertyFilter[]) => {
                const eventProps = value.filter(
                    (prop) =>
                        'type' in prop && (prop.type === 'event' || prop.type === 'feature' || prop.type === 'cohort')
                )
                const otherProps = value.filter(
                    (prop) =>
                        !('type' in prop) ||
                        (prop.type !== 'event' && prop.type !== 'feature' && prop.type !== 'cohort')
                )
                setQuery?.({
                    ...query,
                    properties: otherProps,
                    eventProperties: eventProps,
                })
            }}
            pageKey={`SessionPropertyFilters.${id}`}
            eventNames={query.event ? [query.event] : []}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
