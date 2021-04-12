import React from 'react'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { FilterType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

export function TestAccountFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportTestAccountFiltersUpdated } = useActions(eventUsageLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    const handleChange = (filters: FilterType[]): void => {
        updateCurrentTeam({ test_account_filters: filters })
        reportTestAccountFiltersUpdated(filters)
    }

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                {!currentTeamLoading && (
                    <PropertyFilters
                        pageKey="testaccountfilters"
                        propertyFilters={currentTeam?.test_account_filters}
                        onChange={handleChange}
                    />
                )}
            </div>
        </div>
    )
}
