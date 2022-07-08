import React from 'react'
import { convertPropertiesToPropertyGroup } from 'lib/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyGroupFilters } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { EditorFilterProps } from '~/types'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { groupsModel } from '~/models/groupsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function TrendsGlobalAndOrFilters({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))

    const { allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(featureFlags[FEATURE_FLAGS.SESSION_ANALYSIS] ? [TaxonomicFilterGroupType.Sessions] : []),
    ]

    return (
        <PropertyGroupFilters
            noTitle
            value={convertPropertiesToPropertyGroup(filters.properties)}
            onChange={(properties) => setFilters({ properties })}
            taxonomicGroupTypes={taxonomicGroupTypes}
            pageKey="insight-filters"
            eventNames={allEventNames}
            filters={filters}
            setTestFilters={(testFilters) => setFilters(testFilters)}
        />
    )
}
