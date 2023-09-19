import { PersonsNode, PersonsQuery } from '~/queries/schema'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { AnyPropertyFilter } from '~/types'
import { useState } from 'react'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isPersonsNode, isPersonsQuery } from '~/queries/utils'

interface PersonPropertyFiltersProps {
    query: PersonsNode | PersonsQuery
    setQuery?: (query: PersonsNode | PersonsQuery) => void
}

let uniqueNode = 0
export function PersonPropertyFilters({ query, setQuery }: PersonPropertyFiltersProps): JSX.Element {
    const [id] = useState(uniqueNode++)
    return !query.properties || Array.isArray(query.properties) ? (
        <PropertyFilters
            propertyFilters={query.properties || []}
            onChange={(value: AnyPropertyFilter[]) => {
                if (isPersonsNode(query)) {
                    setQuery?.({
                        ...query,
                        properties: value,
                    } as PersonsNode)
                } else if (isPersonsQuery(query)) {
                    setQuery?.({
                        ...query,
                        properties: value,
                    } as PersonsQuery)
                }
            }}
            pageKey={`PersonPropertyFilters.${id}`}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
            style={{ marginBottom: 0, marginTop: 0 }}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
