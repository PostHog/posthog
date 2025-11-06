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

    return !query.properties || Array.isArray(query.properties) ? (
        <PropertyFilters
            propertyFilters={query.properties || []}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.SessionProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.HogQLExpression,
            ]}
            onChange={(value: AnyPropertyFilter[]) => {
                setQuery?.({ ...query, properties: value })
            }}
            pageKey={`SessionPropertyFilters.${id}`}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
