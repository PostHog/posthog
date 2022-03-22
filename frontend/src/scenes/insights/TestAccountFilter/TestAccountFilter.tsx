import { useValues } from 'kea'
import React from 'react'
import { FilterType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'

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
        <LemonSwitch
            disabled={!hasFilters}
            checked={hasFilters ? !!filters.filter_test_accounts : false}
            onChange={(checked: boolean) => {
                localStorage.setItem('default_filter_test_accounts', checked.toString())
                onChange({ filter_test_accounts: checked })
            }}
            id="test-account-filter"
            type="primary"
            label="Filter out internal and test users"
        />
    )
}
