import { PersonsNode, PersonsQuery } from '~/queries/schema'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PersonPropertyFilter } from '~/types'
import { useState } from 'react'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isPersonsQuery } from '~/queries/utils'

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
            onChange={(value) => {
                setQuery?.({
                    ...query,
                    properties: value as PersonPropertyFilter[],
                })
            }}
            pageKey={`PersonPropertyFilters.${id}`}
            taxonomicGroupTypes={
                isPersonsQuery(query)
                    ? [
                          TaxonomicFilterGroupType.PersonProperties,
                          TaxonomicFilterGroupType.Cohorts,
                          TaxonomicFilterGroupType.HogQLExpression,
                      ]
                    : [TaxonomicFilterGroupType.PersonProperties]
            }
            hogQLTable="persons"
            style={{ marginBottom: 0, marginTop: 0 }}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
