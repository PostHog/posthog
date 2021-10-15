import React from 'react'
import { useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { AnyPropertyFilter } from '~/types'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'

export function PathCleaningFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportTestAccountFiltersUpdated } = useActions(eventUsageLogic)
    const { currentTeam } = useValues(teamLogic)

    const handleChange = (filters: AnyPropertyFilter[]): void => {
        updateCurrentTeam({ test_account_filters: filters })
        reportTestAccountFiltersUpdated(filters)
    }

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                {currentTeam && (
                    <PathCleanFilters
                        pageKey="testaccountfilters"
                        propertyFilters={currentTeam?.test_account_filters}
                        onChange={handleChange}
                    />
                )}
            </div>
        </div>
    )
}
