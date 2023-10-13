import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyGroupFilters } from './PropertyGroupFilters/PropertyGroupFilters'
import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { actionsModel } from '~/models/actionsModel'
import { getAllEventNames } from './utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { EditorFilterProps } from '~/types'
import { StickinessQuery, TrendsQuery } from '~/queries/schema'

export function GlobalAndOrFilters({ insightProps }: EditorFilterProps): JSX.Element {
    const { actions: allActions } = useValues(actionsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { isTrends, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(isTrends ? [TaxonomicFilterGroupType.Sessions] : []),
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    return (
        <PropertyGroupFilters
            pageKey="insight-filters"
            query={querySource as TrendsQuery | StickinessQuery}
            setQuery={updateQuerySource}
            eventNames={getAllEventNames(querySource as TrendsQuery | StickinessQuery, allActions)}
            taxonomicGroupTypes={taxonomicGroupTypes}
            noTitle
        />
    )
}
