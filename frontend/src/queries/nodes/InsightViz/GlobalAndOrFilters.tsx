import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyGroupFilters } from './PropertyGroupFilters/PropertyGroupFilters'
import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { TrendsQuery, StickinessQuery } from '~/queries/schema'
import { isTrendsQuery } from '~/queries/utils'
import { actionsModel } from '~/models/actionsModel'
import { getAllEventNames } from './utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

type GlobalAndOrFiltersProps = {
    query: TrendsQuery | StickinessQuery
}

export function GlobalAndOrFilters({ query }: GlobalAndOrFiltersProps): JSX.Element {
    const { actions: allActions } = useValues(actionsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { updateQuerySource } = useActions(insightVizDataLogic)

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
            setQuery={updateQuerySource}
            eventNames={getAllEventNames(query, allActions)}
            taxonomicGroupTypes={taxonomicGroupTypes}
            noTitle
        />
    )
}
