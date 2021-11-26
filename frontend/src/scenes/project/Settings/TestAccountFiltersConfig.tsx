import React from 'react'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsModel } from '~/models/groupsModel'

export function TestAccountFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportTestAccountFiltersUpdated } = useActions(eventUsageLogic)
    const { currentTeam } = useValues(teamLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const handleChange = (filters: AnyPropertyFilter[]): void => {
        updateCurrentTeam({ test_account_filters: filters })
        reportTestAccountFiltersUpdated(filters)
    }

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                {currentTeam && (
                    <PropertyFilters
                        pageKey="testaccountfilters"
                        propertyFilters={currentTeam?.test_account_filters}
                        onChange={handleChange}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                        ]}
                    />
                )}
            </div>
        </div>
    )
}
