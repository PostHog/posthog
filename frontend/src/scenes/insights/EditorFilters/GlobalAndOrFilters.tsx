import { convertPropertiesToPropertyGroup } from 'lib/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyGroupFilters } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { EditorFilterProps, InsightType } from '~/types'
import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { insightLogic } from 'scenes/insights/insightLogic'

export function GlobalAndOrFilters({ filters }: EditorFilterProps): JSX.Element {
    const { setFiltersMerge } = useActions(insightLogic)
    const { allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(filters.insight === InsightType.TRENDS ? [TaxonomicFilterGroupType.Sessions] : []),
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    return (
        <PropertyGroupFilters
            noTitle
            value={convertPropertiesToPropertyGroup(filters.properties)}
            onChange={(properties) => setFiltersMerge({ properties })}
            taxonomicGroupTypes={taxonomicGroupTypes}
            pageKey="insight-filters"
            eventNames={allEventNames}
            filters={filters}
            setTestFilters={(testFilters) => setFiltersMerge(testFilters)}
        />
    )
}
