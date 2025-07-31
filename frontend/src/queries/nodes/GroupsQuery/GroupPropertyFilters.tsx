import { useState } from 'react'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { GroupsQuery, NodeKind } from '~/queries/schema/schema-general'
import { GroupPropertyFilter } from '~/types'

interface GroupPropertyFiltersProps {
    query: GroupsQuery
    setQuery?: (query: GroupsQuery) => void
}

let uniqueNode = 0
export function GroupPropertyFilters({ query, setQuery }: GroupPropertyFiltersProps): JSX.Element {
    const [id] = useState(uniqueNode++)
    return !query.properties || Array.isArray(query.properties) ? (
        <PropertyFilters
            propertyFilters={query.properties || []}
            onChange={(value) => {
                setQuery?.({
                    ...query,
                    properties: value as GroupPropertyFilter[],
                })
            }}
            pageKey={`GroupPropertyFilters.${id}`}
            taxonomicGroupTypes={[
                `${TaxonomicFilterGroupType.GroupsPrefix}_${query.group_type_index}` as unknown as TaxonomicFilterGroupType,
            ]}
            metadataSource={{ kind: NodeKind.GroupsQuery, group_type_index: query.group_type_index }}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}
