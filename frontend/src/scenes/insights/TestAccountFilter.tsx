import { Switch, Tooltip } from 'antd'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import { FilterType } from '~/types'

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
                    ? 'Filter out test accounts and team members from this query.'
                    : "You don't have a test account filter set up. Click configure to set it up."
            }
        >
            <Switch
                disabled={!hasFilters}
                checked={hasFilters ? filters.filter_test_accounts : false}
                onChange={(checked: boolean) => onChange({ filter_test_accounts: checked })}
                size="small"
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
            >
                <small>
                    Filter out test accounts. <Link to="/project/settings#testaccounts">Configure</Link>
                </small>
            </label>
        </Tooltip>
    )
}
