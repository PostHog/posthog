import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconGear, IconPalette } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider, LemonLabel, LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Popover } from 'lib/lemon-ui/Popover'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardInsightColorsModalLogic } from 'scenes/dashboard/dashboardInsightColorsModalLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardMode, DashboardPlacement } from '~/types'

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
 * used to earn a spot in the bar itself. Hosts the test account filter override and the
 * breakdown color override.
 */
export function DashboardEditBarAdvancedFilters(): JSX.Element {
    const {
        dashboard,
        dashboardMode,
        placement,
        canEditDashboard,
        effectiveEditBarFilters,
        effectiveBreakdownColors,
        dataColorThemeId,
    } = useValues(dashboardLogic)
    const { setFilterTestAccounts, setDashboardMode } = useActions(dashboardLogic)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasDashboardColors = useFeatureFlag('PRODUCT_ANALYTICS_DASHBOARD_COLORS')
    const [visible, setVisible] = useState(false)

    const filterTestAccounts = effectiveEditBarFilters.filterTestAccounts ?? null
    const choice: TestAccountFilterChoice =
        filterTestAccounts === null ? 'inherit' : filterTestAccounts ? 'filter-out' : 'include'
    const hasTestAccountFilters = (currentTeam?.test_account_filters || []).length > 0
    // Only the full dashboard scene mounts DashboardInsightColorsModal, so elsewhere the button would no-op.
    const showColors =
        hasDashboardColors && canEditDashboard && !!dashboard && placement === DashboardPlacement.Dashboard
    // Auto-assigned colors aren't an override — only pinned values and a picked theme are.
    const hasColorOverrides =
        effectiveBreakdownColors.some((config) => config.source !== 'auto') || dataColorThemeId != null
    const overrideCount = (choice === 'inherit' ? 0 : 1) + (showColors && hasColorOverrides ? 1 : 0)

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="bottom-end"
            overlay={
                <div className="flex w-80 flex-col gap-2 p-2">
                    <div>
                        <h4 className="mb-0 font-semibold">Advanced options</h4>
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
                    {showColors && (
                        <>
                            <LemonDivider className="my-0" />
                            <LemonLabel info="Pin a breakdown value to a color, or pick a color theme, so every insight on this dashboard draws it the same way.">
                                Breakdown colors
                            </LemonLabel>
                            <LemonButton
                                type="secondary"
                                size="small"
                                fullWidth
                                center
                                icon={<IconPalette />}
                                onClick={() => {
                                    setVisible(false)
                                    showInsightColorsModal(dashboard.id)
                                }}
                                data-attr="dashboard-advanced-customize-colors"
                            >
                                Customize colors
                            </LemonButton>
                        </>
                    )}
                </div>
            }
        >
            <LemonButton
                size="small"
                icon={<IconEllipsis />}
                tooltip="Advanced options"
                active={visible}
                onClick={() => setVisible(!visible)}
                sideIcon={overrideCount ? <LemonBadge.Number count={overrideCount} size="small" /> : undefined}
                data-attr="dashboard-advanced-filters"
            />
        </Popover>
    )
}
