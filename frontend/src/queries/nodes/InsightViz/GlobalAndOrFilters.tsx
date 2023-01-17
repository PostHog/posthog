import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyGroupFilters } from './PropertyGroupFilters/PropertyGroupFilters'
import { useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { StickinessQuery, TrendsQuery } from '~/queries/schema'
import { isTrendsQuery } from '~/queries/utils'
import { actionsModel } from '~/models/actionsModel'
import { getAllEventNames } from './utils'

type GlobalAndOrFiltersProps = {
    query: TrendsQuery | StickinessQuery
    setQuery: (node: TrendsQuery | StickinessQuery) => void
}

export function GlobalAndOrFilters({ query, setQuery }: GlobalAndOrFiltersProps): JSX.Element {
    const { actions: allActions } = useValues(actionsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(isTrendsQuery(query) ? [TaxonomicFilterGroupType.Sessions] : []),
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    return (
        <PropertyGroupFilters
            pageKey="insight-filters"
            query={query}
            setQuery={setQuery}
            eventNames={getAllEventNames(query, allActions)}
            taxonomicGroupTypes={taxonomicGroupTypes}
            noTitle
        />
    )
}
