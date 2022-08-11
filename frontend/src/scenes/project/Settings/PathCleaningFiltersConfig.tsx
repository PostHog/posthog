import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'

export function PathCleaningFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, pathCleaningFiltersWithNew } = useValues(teamLogic)

    const handleChange = (filters: Record<string, any>[]): void => {
        updateCurrentTeam({ path_cleaning_filters: filters })
    }

    const onRemove = (index: number): void => {
        const newState = (currentTeam?.path_cleaning_filters || []).filter((_, i) => i !== index)
        handleChange(newState)
    }
    const onCopy = (index: number): void => {
        const newState = currentTeam?.path_cleaning_filters
            ? (currentTeam.path_cleaning_filters = [
                  ...currentTeam.path_cleaning_filters,
                  currentTeam.path_cleaning_filters[index],
              ])
            : []
        handleChange(newState)
    }

    return (
        <div style={{ marginBottom: 16 }}>
            {currentTeam && (
                <PathCleanFilters
                    pageKey="pathcleanfilters"
                    pathCleaningFilters={pathCleaningFiltersWithNew}
                    onChange={(newItem) => {
                        handleChange([...(currentTeam?.path_cleaning_filters || []), newItem])
                    }}
                    onRemove={onRemove}
                    onCopy={onCopy}
                />
            )}
        </div>
    )
}
