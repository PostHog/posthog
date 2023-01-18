import { useState } from 'react'
import { useActions, useValues } from 'kea'

import { pathsLogic } from 'scenes/paths/pathsLogic'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { EditorFilterProps, PathsFilterType, QueryEditorFilterProps } from '~/types'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { Popup } from 'lib/components/Popup/Popup'
import { PathRegexPopup } from 'lib/components/PathCleanFilters/PathCleanFilter'
import { IconPlus } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'

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
    const [open, setOpen] = useState(false)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.path_cleaning_filters || []).length > 0

    return (
        <div>
            <PathCleanFilters
                pageKey="pathcleanfilters-local"
                pathCleaningFilters={local_path_cleaning_filters || []}
                onChange={(newItem) => {
                    setFilter({
                        local_path_cleaning_filters: [...(local_path_cleaning_filters || []), newItem],
                    })
                }}
                onRemove={(index) => {
                    const newState = (local_path_cleaning_filters || []).filter((_, i) => i !== index)
                    setFilter({ local_path_cleaning_filters: newState })
                }}
            />
            <Popup
                visible={open}
                placement="top-end"
                fallbackPlacements={['top-start']}
                onClickOutside={() => setOpen(false)}
                overlay={
                    <PathRegexPopup
                        item={{}}
                        onClose={() => setOpen(false)}
                        onComplete={(newItem) => {
                            setFilter({
                                local_path_cleaning_filters: [...(local_path_cleaning_filters || []), newItem],
                            })
                            setOpen(false)
                        }}
                    />
                }
            >
                <LemonButton
                    onClick={() => setOpen(!open)}
                    className={`mb-4 ${(local_path_cleaning_filters || []).length > 0 && 'mt-2'}`}
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
                    checked={hasFilters ? path_replacements || false : false}
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
