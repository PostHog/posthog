import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'

export function PathCleaningFiltersConfig(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam) {
        return null
    }

    return (
        <PathCleanFilters
            filters={currentTeam.path_cleaning_filters}
            setFilters={(filters) => {
                updateCurrentTeam({ path_cleaning_filters: filters })
            }}
        />
    )
}
