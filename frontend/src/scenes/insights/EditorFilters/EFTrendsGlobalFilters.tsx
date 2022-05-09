import React from 'react'
import { convertPropertyGroupToProperties } from 'lib/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EditorFilterProps } from '~/types'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { groupsModel } from '~/models/groupsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'

export function EFTrendsGlobalFilters({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const { allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    return (
        <>
            <PropertyFilters
                propertyFilters={convertPropertyGroupToProperties(filters.properties)}
                onChange={(properties) => setFilters({ properties })}
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                ]}
                pageKey="trends-filters"
                eventNames={allEventNames}
            />
            <TestAccountFilter filters={filters} onChange={setFilters} />
        </>
    )
}
