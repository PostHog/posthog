import { PersonsNode } from '~/queries/schema'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { AnyPropertyFilter } from '~/types'
import { useState } from 'react'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

interface PersonPropertyFiltersProps {
    query: PersonsNode
    setQuery?: (query: PersonsNode) => void
}

let uniqueNode = 0
export function PersonPropertyFilters({ query, setQuery }: PersonPropertyFiltersProps): JSX.Element {
    const [id] = useState(uniqueNode++)
    return !query.properties || Array.isArray(query.properties) ? (
        <PropertyFilters
            propertyFilters={query.properties || []}
            onChange={(value: AnyPropertyFilter[]) => setQuery?.({ ...query, properties: value })}
            pageKey={`PersonPropertyFilters.${id}`}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
            style={{ marginBottom: 0, marginTop: 0 }}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
