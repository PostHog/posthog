import { Row, Switch } from 'antd'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import React from 'react'
import { FilterType } from '~/types'
import { SettingOutlined } from '@ant-design/icons'
import { teamLogic } from 'scenes/teamLogic'
import { Tooltip } from 'lib/components/Tooltip'

export function TestAccountFilter({
    filters,
    onChange,
}: {
    filters: Partial<FilterType>
    onChange: (filters: Partial<FilterType>) => void
}): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    return (
        <Tooltip
            title={
                hasFilters
                    ? 'Filter out internal test and team members users from this query.'
                    : "You don't have internal users filtering set up. Click the gear icon to configure it."
            }
        >
            <Row style={{ alignItems: 'center', flexWrap: 'nowrap' }}>
                <Switch
                    disabled={!hasFilters}
                    checked={hasFilters ? filters.filter_test_accounts : false}
                    onChange={(checked: boolean) => {
                        localStorage.setItem('default_filter_test_accounts', checked.toString())
                        onChange({ filter_test_accounts: checked })
                    }}
                    size="small"
                />
                <label
                    style={{
                        marginLeft: 10,
                    }}
                >
                    Filter out internal and test users
                </label>
                <Link to="/project/settings#internal-users-filtering">
                    <SettingOutlined
                        style={{
                            marginLeft: 8,
                        }}
                    />
                </Link>
            </Row>
        </Tooltip>
    )
}
