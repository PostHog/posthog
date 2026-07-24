import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconGear } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider, LemonLabel, LemonSegmentedButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardMode } from '~/types'

type TestAccountFilterChoice = 'inherit' | 'filter-out' | 'include'

const CHOICE_TO_FILTER: Record<TestAccountFilterChoice, boolean | null> = {
    inherit: null,
    'filter-out': true,
    include: false,
}

const CHOICE_HINTS: Record<TestAccountFilterChoice, string> = {
    inherit: 'Each insight keeps its own "Filter out internal and test users" setting.',
    'filter-out': 'Internal and test users are filtered out of every insight on this dashboard.',
    include: 'Internal and test users are included in every insight on this dashboard.',
}

/**
 * "…" at the end of the dashboard edit bar, opening a panel for overrides that are too rarely
 * used to earn a spot in the bar itself. Currently hosts the test account filter override.
 */
export function DashboardEditBarAdvancedFilters(): JSX.Element {
    const { dashboardMode, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setFilterTestAccounts, setDashboardMode } = useActions(dashboardLogic)
    const { currentTeam } = useValues(teamLogic)
    const [visible, setVisible] = useState(false)

    const filterTestAccounts = effectiveEditBarFilters.filterTestAccounts ?? null
    const choice: TestAccountFilterChoice =
        filterTestAccounts === null ? 'inherit' : filterTestAccounts ? 'filter-out' : 'include'
    const overrideCount = choice === 'inherit' ? 0 : 1
    const hasTestAccountFilters = (currentTeam?.test_account_filters || []).length > 0

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="bottom-end"
            overlay={
                <div className="flex w-80 flex-col gap-2 p-2">
                    <div>
                        <h4 className="mb-0 font-semibold">Advanced filters</h4>
                        <p className="mb-0 text-xs text-secondary">
                            Overrides applied to every insight on this dashboard.
                        </p>
                    </div>
                    <LemonDivider className="my-0" />
                    <div className="flex items-center justify-between gap-2">
                        <LemonLabel info="Force test account filtering on or off for every insight, or let each insight keep its own setting.">
                            Test account filtering
                        </LemonLabel>
                        <LemonButton
                            icon={<IconGear />}
                            size="xsmall"
                            noPadding
                            to={urls.settings('project-product-analytics', 'internal-user-filtering')}
                            tooltip="Configure internal and test account filters"
                        />
                    </div>
                    <LemonSegmentedButton<TestAccountFilterChoice>
                        fullWidth
                        size="small"
                        value={choice}
                        onChange={(next) => {
                            if (dashboardMode !== DashboardMode.Edit) {
                                setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
                            }
                            setFilterTestAccounts(CHOICE_TO_FILTER[next])
                        }}
                        options={[
                            {
                                value: 'inherit',
                                label: 'Inherit',
                                tooltip: 'Each insight keeps its own setting',
                                'data-attr': 'dashboard-test-account-filter-inherit',
                            },
                            {
                                value: 'filter-out',
                                label: 'Filter out',
                                tooltip: 'Force test account filtering on for every insight',
                                disabledReason: !hasTestAccountFilters
                                    ? "You haven't set any internal test filters. Click the gear icon to configure."
                                    : undefined,
                                'data-attr': 'dashboard-test-account-filter-out',
                            },
                            {
                                value: 'include',
                                label: 'Include',
                                tooltip: 'Force test account filtering off for every insight',
                                'data-attr': 'dashboard-test-account-filter-include',
                            },
                        ]}
                    />
                    <p className="mb-0 text-xs text-secondary">{CHOICE_HINTS[choice]}</p>
                </div>
            }
        >
            <LemonButton
                size="small"
                icon={<IconEllipsis />}
                tooltip="Advanced filters"
                active={visible}
                onClick={() => setVisible(!visible)}
                sideIcon={overrideCount ? <LemonBadge.Number count={overrideCount} size="small" /> : undefined}
                data-attr="dashboard-advanced-filters"
            />
        </Popover>
    )
}
