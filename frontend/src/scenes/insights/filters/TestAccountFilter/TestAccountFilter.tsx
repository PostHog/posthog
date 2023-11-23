import { useActions, useValues } from 'kea'
import { IconSettings } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FilterType } from '~/types'

export function TestAccountFilter({
    filters,
    onChange,
    disabledReason,
}: {
    filters: Partial<FilterType>
    onChange: (filters: Partial<FilterType>) => void
    disabledReason?: string | null | false
}): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)

    return (
        <LemonSwitch
            checked={hasFilters ? !!filters.filter_test_accounts : false}
            onChange={(checked: boolean) => {
                onChange({ filter_test_accounts: checked })
                setLocalDefault(checked)
            }}
            id="test-account-filter"
            bordered
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    <LemonButton
                        icon={<IconSettings />}
                        to={urls.settings('project-product-analytics', 'internal-user-filtering')}
                        status="stealth"
                        size="small"
                        noPadding
                        className="ml-1"
                    />
                </div>
            }
            fullWidth
            disabledReason={!hasFilters ? "You haven't set any internal and test filters" : disabledReason}
        />
    )
}
