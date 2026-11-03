import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconFlask, IconGear } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

import { FilterBarOptionControl } from 'lib/components/FilterBar/FilterBarOptionControl'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function DashboardTestAccountsControl(): JSX.Element | null {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setFilterTestAccounts, setDashboardEditing } = useActions(dashboardLogic)
    const { currentTeam } = useValues(teamLogic)
    const filterTestAccounts = effectiveEditBarFilters.filterTestAccounts ?? null
    const hasTestAccountFilters = (currentTeam?.test_account_filters || []).length > 0

    return (
        <FilterBarOptionControl
            id="test-accounts"
            label="Test accounts"
            icon={IconFlask}
            value={filterTestAccounts === null ? null : filterTestAccounts ? 'filter-out' : 'include'}
            options={[
                {
                    value: 'filter-out',
                    label: 'Filtered out',
                    disabledReason: hasTestAccountFilters
                        ? undefined
                        : "You haven't set up any internal or test account filters yet",
                },
                { value: 'include', label: 'Included' },
            ]}
            onChange={(next) => {
                if (!dashboardEditing?.filters) {
                    setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
                }
                setFilterTestAccounts(next === null ? null : next === 'filter-out')
            }}
            footer={
                <DropdownMenuItem
                    onClick={() =>
                        router.actions.push(urls.settings('project-product-analytics', 'internal-user-filtering'))
                    }
                    data-attr="dashboard-test-account-filter-settings"
                >
                    <IconGear />
                    Configure test accounts
                </DropdownMenuItem>
            }
            data-attr="dashboard-test-account-filter"
        />
    )
}
