import { useActions, useValues } from 'kea'

import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { QueryEditorFilterProps } from '~/types'
import { LemonSwitch } from '@posthog/lemon-ui'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PathsFilter } from '~/queries/schema'

export function PathCleaningFilter({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { local_path_cleaning_filters, path_replacements } = (insightFilter || {}) as PathsFilter

    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.path_cleaning_filters || []).length > 0

    return (
        <>
            <PathCleanFilters
                filters={local_path_cleaning_filters}
                setFilters={(filters) => updateInsightFilter({ local_path_cleaning_filters: filters })}
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
                            updateInsightFilter({ path_replacements: checked })
                        }}
                        label="Apply global path URL cleaning"
                        bordered
                    />
                </div>
            </Tooltip>
        </>
    )
}
