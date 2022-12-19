import { useState } from 'react'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { Popup } from 'lib/components/Popup/Popup'
import { PathRegexPopup } from 'lib/components/PathCleanFilters/PathCleanFilter'
import { useActions, useValues } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { IconPlus } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'

export function PathCleaningFilter(): JSX.Element {
    const [open, setOpen] = useState(false)
    const { insightProps } = useValues(insightLogic)
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.path_cleaning_filters || []).length > 0

    return (
        <div className="space-y-2">
            <PathCleanFilters
                pageKey="pathcleanfilters-local"
                pathCleaningFilters={filter.local_path_cleaning_filters || []}
                onChange={(newItem) => {
                    setFilter({
                        local_path_cleaning_filters: [...(filter.local_path_cleaning_filters || []), newItem],
                    })
                }}
                onRemove={(index) => {
                    const newState = (filter.local_path_cleaning_filters || []).filter((_, i) => i !== index)
                    setFilter({ local_path_cleaning_filters: newState })
                }}
            />
            <Popup
                visible={open}
                placement={'top-end'}
                fallbackPlacements={['top-start']}
                onClickOutside={() => setOpen(false)}
                overlay={
                    <PathRegexPopup
                        item={{}}
                        onClose={() => setOpen(false)}
                        onComplete={(newItem) => {
                            setFilter({
                                local_path_cleaning_filters: [...(filter.local_path_cleaning_filters || []), newItem],
                            })
                            setOpen(false)
                        }}
                    />
                }
            >
                <LemonButton
                    onClick={() => setOpen(!open)}
                    className="new-prop-filter"
                    data-attr={'new-prop-filter-' + 'pathcleanfilters-local'}
                    type="secondary"
                    icon={<IconPlus />}
                    size="small"
                >
                    Add Rule
                </LemonButton>
            </Popup>

            <Tooltip
                title={
                    hasFilters
                        ? 'Clean paths based using regex replacement.'
                        : "You don't have path cleaning filters. Click the gear icon to configure it."
                }
            >
                <LemonSwitch
                    disabled={!hasFilters}
                    checked={hasFilters ? filter.path_replacements || false : false}
                    onChange={(checked: boolean) => {
                        localStorage.setItem('default_path_clean_filters', checked.toString())
                        setFilter({ path_replacements: checked })
                    }}
                    label="Apply global path URL cleaning"
                    bordered
                />
            </Tooltip>
        </div>
    )
}
