// import { convertPropertiesToPropertyGroup } from 'lib/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyGroupFilters } from './PropertyGroupFilters/PropertyGroupFilters'
// import { EditorFilterProps, InsightType } from '~/types'
import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { TrendsQuery, StickinessQuery } from '~/queries/schema'
import { isTrendsQuery } from '~/queries/utils'
// import { insightLogic } from 'scenes/insights/insightLogic'

type GlobalAndOrFiltersProps = {
    query: TrendsQuery | StickinessQuery
    setQuery: (node: TrendsQuery | StickinessQuery) => void
    // insightProps
}

export function GlobalAndOrFilters({ query, setQuery }: GlobalAndOrFiltersProps): JSX.Element {
    // const { setFiltersMerge } = useActions(insightLogic)
    // const { allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(isTrendsQuery(query) ? [TaxonomicFilterGroupType.Sessions] : []),
    ]

    return (
        <PropertyGroupFilters
            pageKey="insight-filters"
            query={query}
            setQuery={setQuery}
            // value={convertPropertiesToPropertyGroup(filters.properties)}
            // onChange={(properties) => setFiltersMerge({ properties })}
            // eventNames={allEventNames}
            taxonomicGroupTypes={taxonomicGroupTypes}
            noTitle
        />
    )
}
