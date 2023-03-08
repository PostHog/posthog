import { useValues } from 'kea'
import { FilterType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconSettings } from 'lib/lemon-ui/icons'

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
            checked={hasFilters ? !!filters.filter_test_accounts : false}
            onChange={(checked: boolean) => {
                localStorage.setItem('default_filter_test_accounts', checked.toString())
                onChange({ filter_test_accounts: checked })
            }}
            id="test-account-filter"
            bordered
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    <LemonButton
                        icon={<IconSettings />}
                        to="/project/settings#internal-users-filtering"
                        status="stealth"
                        size="small"
                        noPadding
                        className="ml-1"
                    />
                </div>
            }
            fullWidth
            disabled={!hasFilters}
        />
    )
}
