import { Row, Switch } from 'antd'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import React from 'react'
import { FilterType } from '~/types'
import { SettingOutlined } from '@ant-design/icons'
import { teamLogic } from 'scenes/teamLogic'
import { Tooltip } from 'lib/components/Tooltip'

export function PathCleanFilter({
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
            <Row style={{ alignItems: 'center', flexWrap: 'nowrap', justifyContent: 'flex-end' }}>
                <Link to="/project/settings#path_cleaning_filtering">
                    <SettingOutlined
                        style={{
                            marginLeft: 8,
                        }}
                    />
                </Link>
                <label
                    style={{
                        marginLeft: 10,
                        marginRight: 10,
                    }}
                >
                    Apply path URL cleaning
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
