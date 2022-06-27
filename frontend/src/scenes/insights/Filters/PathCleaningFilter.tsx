import React, { useState } from 'react'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { Button, Row, Tooltip } from 'antd'
import { Popup } from 'lib/components/Popup/Popup'
import { PathRegexPopup } from 'lib/components/PathCleanFilters/PathCleanFilter'
import { PlusCircleOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSwitch } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'

export function PathCleaningFilter(): JSX.Element {
    const [open, setOpen] = useState(false)
    const { insightProps } = useValues(insightLogic)
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.path_cleaning_filters || []).length > 0

    return (
        <>
            <PathCleanFilters
                style={{ paddingLeft: 10 }}
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
            <Row align="middle" justify="space-between" style={{ paddingLeft: 0 }}>
                <Popup
                    visible={open}
                    placement={'bottom-end'}
                    fallbackPlacements={['bottom-start']}
                    onClickOutside={() => setOpen(false)}
                    overlay={
                        <PathRegexPopup
                            item={{}}
                            onClose={() => setOpen(false)}
                            onComplete={(newItem) => {
                                setFilter({
                                    local_path_cleaning_filters: [
                                        ...(filter.local_path_cleaning_filters || []),
                                        newItem,
                                    ],
                                })
                                setOpen(false)
                            }}
                        />
                    }
                >
                    <Button
                        onClick={() => setOpen(!open)}
                        className="new-prop-filter"
                        data-attr={'new-prop-filter-' + 'pathcleanfilters-local'}
                        type="link"
                        style={{ paddingLeft: 0 }}
                        icon={<PlusCircleOutlined />}
                    >
                        {'Add Rule'}
                    </Button>
                </Popup>

                <Tooltip
                    title={
                        hasFilters
                            ? 'Clean paths based using regex replacement.'
                            : "You don't have path cleaning filters. Click the gear icon to configure it."
                    }
                >
                    <div className="flex gap">
                        <label>Apply global path URL cleaning</label>
                        <LemonSwitch
                            disabled={!hasFilters}
                            checked={hasFilters ? filter.path_replacements || false : false}
                            onChange={(checked: boolean) => {
                                localStorage.setItem('default_path_clean_filters', checked.toString())
                                setFilter({ path_replacements: checked })
                            }}
                            size="small"
                        />
                    </div>
                </Tooltip>
            </Row>
        </>
    )
}
