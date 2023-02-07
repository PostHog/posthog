import { useActions, useValues } from 'kea'

import { pathsLogic } from 'scenes/paths/pathsLogic'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { EditorFilterProps, PathsFilterType, QueryEditorFilterProps } from '~/types'
import { LemonSwitch } from '@posthog/lemon-ui'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function PathCleaningFilterDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return <PathCleaningFilterComponent setFilter={updateInsightFilter} {...insightFilter} />
}

export function PathCleaningFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return <PathCleaningFilterComponent setFilter={setFilter} {...filter} />
}

type PathCleaningFilterComponentProps = {
    setFilter: (filter: PathsFilterType) => void
} & PathsFilterType

export function PathCleaningFilterComponent({
    setFilter,
    local_path_cleaning_filters,
    path_replacements,
}: PathCleaningFilterComponentProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.path_cleaning_filters || []).length > 0

    return (
        <>
            <PathCleanFilters
                filters={local_path_cleaning_filters}
                setFilters={(filters) => setFilter({ local_path_cleaning_filters: filters })}
            />
            <Tooltip
                title={
                    hasFilters
                        ? 'Clean paths based using regex replacement.'
                        : "You don't have path cleaning filters. Click the gear icon to configure it."
                }
            >
                {/* This div is necessary for the tooltip to work. */}
                <div className="inline-block mt-4">
                    <LemonSwitch
                        disabled={!hasFilters}
                        checked={hasFilters ? path_replacements || false : false}
                        onChange={(checked: boolean) => {
                            localStorage.setItem('default_path_clean_filters', checked.toString())
                            setFilter({ path_replacements: checked })
                        }}
                        label="Apply global path URL cleaning"
                        bordered
                    />
                </div>
            </Tooltip>
        </>
    )
}
