import { Row, Switch, Tooltip } from 'antd'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import { FilterType } from '~/types'
import { SettingOutlined } from '@ant-design/icons'

export function TestAccountFilter({
    filters,
    onChange,
}: {
    filters: Partial<FilterType>
    onChange: (filters: Partial<FilterType>) => void
}): JSX.Element | null {
    const { user } = useValues(userLogic)
    const hasFilters = (user?.team?.test_account_filters || []).length > 0

    return (
        <Tooltip
            title={
                hasFilters
                    ? 'Filter out internal test and team members users from this query.'
                    : "You don't have internal users filtering set up. Click the gear icon to configure it."
            }
        >
            <Row style={{ alignItems: 'center' }}>
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
                    Filter out internal users
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
