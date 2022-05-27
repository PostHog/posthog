import { useValues } from 'kea'
import React from 'react'
import { FilterType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { LemonButton } from 'lib/components/LemonButton'
import { IconSettings } from 'lib/components/icons'

export function TestAccountFilter({
    filters,
    onChange,
    className,
}: {
    filters: Partial<FilterType>
    onChange: (filters: Partial<FilterType>) => void
    className?: string
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
            label={
                <div className="flex-center">
                    <span>Filter out internal and test users</span>
                    <LemonButton
                        icon={<IconSettings />}
                        to="/project/settings#internal-users-filtering"
                        type="stealth"
                        size="small"
                        className="ml-025"
                    />
                </div>
            }
            style={{ width: '100%' }}
            className={className}
        />
    )
}
