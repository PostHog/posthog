import { Row, Switch } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { FilterType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { Tooltip } from 'lib/components/Tooltip'

export function PathCleanFilterToggle({
    filters,
    onChange,
}: {
    filters: Partial<FilterType>
    onChange: (filters: Partial<FilterType>) => void
}): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.path_cleaning_filters || []).length > 0

    return (
        <Tooltip
            title={
                hasFilters
                    ? 'Clean paths based using regex replacement.'
                    : "You don't have path cleaning filters. Click the gear icon to configure it."
            }
        >
            <Row style={{ alignItems: 'center', flexWrap: 'nowrap', justifyContent: 'flex-end', paddingRight: 0 }}>
                <label
                    style={{
                        marginLeft: 10,
                        marginRight: 10,
                    }}
                >
                    Apply global path URL cleaning
                </label>
                <Switch
                    disabled={!hasFilters}
                    checked={hasFilters ? filters.path_replacements : false}
                    onChange={(checked: boolean) => {
                        localStorage.setItem('default_path_clean_filters', checked.toString())
                        onChange({ path_replacements: checked })
                    }}
                    size="small"
                />
            </Row>
        </Tooltip>
    )
}
