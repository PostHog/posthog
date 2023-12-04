import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { StickinessQuery, TrendsQuery } from '~/queries/schema'
import { EditorFilterProps } from '~/types'

import { PropertyGroupFilters } from './PropertyGroupFilters/PropertyGroupFilters'
import { getAllEventNames } from './utils'

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
            insightProps={insightProps}
            pageKey={`${keyForInsightLogicProps('new')(insightProps)}-GlobalAndOrFilters`}
            query={querySource as TrendsQuery | StickinessQuery}
            setQuery={updateQuerySource}
            eventNames={getAllEventNames(querySource as TrendsQuery | StickinessQuery, allActions)}
            taxonomicGroupTypes={taxonomicGroupTypes}
        />
    )
}
