import { useState } from 'react'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { ActorsQuery, NodeKind, PersonsNode } from '~/queries/schema/schema-general'
import { isActorsQuery } from '~/queries/utils'
import { PersonPropertyFilter } from '~/types'

interface PersonPropertyFiltersProps {
    query: PersonsNode | ActorsQuery
    setQuery?: (query: PersonsNode | ActorsQuery) => void
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
                isActorsQuery(query)
                    ? [
                          TaxonomicFilterGroupType.PersonProperties,
                          TaxonomicFilterGroupType.Cohorts,
                          TaxonomicFilterGroupType.HogQLExpression,
                      ]
                    : [TaxonomicFilterGroupType.PersonProperties]
            }
            metadataSource={{ kind: NodeKind.ActorsQuery }}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
