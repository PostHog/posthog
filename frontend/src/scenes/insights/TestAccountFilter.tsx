import { Switch } from 'antd'
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
}): JSX.element {
    const { user } = useValues(userLogic)
    if (!user?.team?.test_account_filters) {
        return null
    }
    return (
        <>
            <hr />
            <Switch
                checked={filters.filter_test_accounts}
                onChange={(checked: boolean) => onChange({ filter_test_accounts: checked })}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
            >
                Filter out test accounts. <Link to="/project/settings#testaccounts">Configure</Link>
            </label>
        </>
    )
}
