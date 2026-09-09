import { useActions, useValues } from 'kea'

import { IconGear, IconPeople } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardMode } from '~/types'

/** Dashboard-wide control for whether insights count internal and test users. */
export function DashboardTestAccountsFilter(): JSX.Element {
    const { dashboardMode, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setFilterTestAccounts, setDashboardMode } = useActions(dashboardLogic)
    const { currentTeam } = useValues(teamLogic)

    const hasTestAccountFilters = (currentTeam?.test_account_filters || []).length > 0

    return (
        <LemonSelect<boolean | null>
            size="small"
            icon={<IconPeople />}
            value={effectiveEditBarFilters.filterTestAccounts ?? null}
            dropdownMatchSelectWidth={false}
            onChange={(filterTestAccounts) => {
                if (dashboardMode !== DashboardMode.Edit) {
                    setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
                }
                setFilterTestAccounts(filterTestAccounts)
            }}
            data-attr="dashboard-test-account-filter"
            options={[
                {
                    options: [
                        {
                            value: null,
                            label: "each insight's test user setting",
                            'data-attr': 'dashboard-test-account-filter-inherit',
                        },
                        {
                            value: true,
                            label: 'internal and test users excluded',
                            disabledReason: !hasTestAccountFilters
                                ? "You haven't set any internal and test user filters yet."
                                : undefined,
                            'data-attr': 'dashboard-test-account-filter-out',
                        },
                        {
                            value: false,
                            label: 'internal and test users included',
                            'data-attr': 'dashboard-test-account-filter-include',
                        },
                    ],
                    footer: (
                        <LemonButton
                            icon={<IconGear />}
                            size="xsmall"
                            fullWidth
                            to={urls.settings('project-product-analytics', 'internal-user-filtering')}
                        >
                            Configure internal and test users
                        </LemonButton>
                    ),
                },
            ]}
        />
    )
}
