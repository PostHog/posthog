import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { IconSettings } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EditorFilterProps } from '~/types'

export function PathCleaningFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { local_path_cleaning_filters, path_replacements } = pathsFilter || {}

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
                        : "You don't have path cleaning filters. Configure via gear icon."
                }
            >
                {/* This div is necessary for the tooltip to work. */}
                <div className="inline-block mt-4 w-full">
                    <LemonSwitch
                        disabled={!hasFilters}
                        checked={hasFilters ? path_replacements || false : false}
                        onChange={(checked: boolean) => {
                            localStorage.setItem('default_path_clean_filters', checked.toString())
                            updateInsightFilter({ path_replacements: checked })
                        }}
                        label={
                            <div className="flex items-center">
                                <span>Apply global path URL cleaning</span>
                                <LemonButton
                                    icon={<IconSettings />}
                                    to={urls.settings('project-product-analytics', 'path-cleaning')}
                                    size="small"
                                    noPadding
                                    className="ml-1"
                                />
                            </div>
                        }
                        fullWidth
                        bordered
                    />
                </div>
            </Tooltip>
        </>
    )
}
