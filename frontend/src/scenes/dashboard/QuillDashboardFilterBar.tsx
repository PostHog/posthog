import clsx from 'clsx'
import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { isDashboardControlHidden } from 'scenes/dashboard/dashboardControls'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'

import { DashboardUnsavedChangesIndicator } from 'products/dashboards/frontend/dashboardSettings/DashboardUnsavedChangesIndicator'

import { QuillDashboardDateFilter } from './QuillDashboardDateFilter'
import { QuillDashboardFilterChips } from './QuillDashboardFilterChips'
import { QuillDashboardFiltersPopover } from './QuillDashboardFiltersPopover'
import { QuillDashboardReloadAction } from './QuillDashboardReloadAction'

/**
 * The dashboard filter bar on the today-rail-nav path. The date range and the dashboard variables stay
 * visible. Every other override goes behind one "Filters" control, and the overrides in force show as chips.
 */
export function QuillDashboardFilterBar(): JSX.Element {
    const { dashboard, effectiveEditBarFilters, dashboardControlScopes, hasVariables } = useValues(dashboardLogic)
    const controlsEnabled = useFeatureFlag('METRICS_DASHBOARD_CONTROLS')

    const hasDateOverride = !!effectiveEditBarFilters.date_from || !!effectiveEditBarFilters.date_to
    const showDateFilter = !(
        controlsEnabled && isDashboardControlHidden(dashboardControlScopes.dateRange, hasDateOverride)
    )

    return (
        <div
            className="@container/dashboard-filters flex min-w-0 flex-1 flex-wrap items-start justify-between gap-2"
            data-quill
        >
            <div className="flex min-w-0 flex-1 flex-wrap items-end gap-2">
                {dashboard && (
                    <>
                        {showDateFilter && <QuillDashboardDateFilter />}
                        <VariablesForDashboard />
                        <QuillDashboardFilterChips />
                        <QuillDashboardFiltersPopover />
                    </>
                )}
                <DashboardUnsavedChangesIndicator />
            </div>
            {/* Variables put a label above their control, so the refresh control drops to line up with the controls. */}
            <div className={clsx('ml-auto flex shrink-0 items-center', hasVariables && 'mt-7')}>
                <QuillDashboardReloadAction />
            </div>
        </div>
    )
}
