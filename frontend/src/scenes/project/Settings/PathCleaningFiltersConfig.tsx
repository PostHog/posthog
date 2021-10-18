import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'

export function PathCleaningFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const handleChange = (filters: Record<string, any>[]): void => {
        updateCurrentTeam({ path_cleaning_filters: filters })
    }

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                {currentTeam && <PathCleanFilters pageKey="testaccountfilters" onChange={handleChange} />}
            </div>
        </div>
    )
}
