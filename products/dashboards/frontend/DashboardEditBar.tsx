import clsx from 'clsx'
import { useValues } from 'kea'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { DashboardPlacement } from '~/types'

import { DashboardMetricVariables } from 'products/metrics/frontend/components/dashboardVariables/DashboardMetricVariables'

import { DashboardActiveFilterChips } from './DashboardActiveFilterChips'
import { DashboardControlSlot } from './DashboardControlSlot'
import { DashboardDateFilter } from './DashboardDateFilter'
import { DashboardEditBarAdvancedFilters } from './DashboardEditBarAdvancedFilters'
import { DashboardFiltersMenu } from './DashboardFiltersMenu'
import { DashboardScopeFilters } from './DashboardScopeFilters'
import { QuillDashboardUnsavedChangesActions } from './dashboardSettings/QuillDashboardUnsavedChangesActions'

interface DashboardEditBarProps {
    showDateFilter?: boolean
    className?: string
}

export function DashboardEditBar({ showDateFilter = true, className }: DashboardEditBarProps): JSX.Element {
    const { dashboardEditing, hasVariables, effectiveEditBarFilters, placement, dashboardSettingsState } =
        useValues(dashboardLogic)
    const controlsEnabled = useFeatureFlag('METRICS_DASHBOARD_CONTROLS')
    const quillSurface = useQuillSurface()
    const showSaveActions =
        quillSurface && placement === DashboardPlacement.Dashboard && dashboardSettingsState === 'unsavedChanges'

    const editingFrameClass = dashboardEditing
        ? clsx(quillSurface ? '-my-2 -ml-2 p-2' : '-m-1.5 p-1.5', 'border-primary border-dashed rounded-lg')
        : 'border-transparent'

    // The breakpoints track the `dashboard-filters` container in DashboardFilterBar. Variables need more room
    // in the row, so the scope filters fold into the "Filters" menu at a wider width when the dashboard has them.
    return (
        <div
            className={
                className ??
                clsx('flex gap-2 items-center flex-wrap', quillSurface && 'min-w-0', 'border', editingFrameClass)
            }
        >
            <div className="contents @max-md/dashboard-filters:hidden">
                <VariablesForDashboard inlineLabels />
                {showDateFilter && <DashboardDateFilter withShortcut />}
                <div
                    className={
                        hasVariables
                            ? 'contents @max-6xl/dashboard-filters:hidden'
                            : 'contents @max-4xl/dashboard-filters:hidden'
                    }
                >
                    <DashboardScopeFilters showIntervalFilter={showDateFilter} />
                </div>
                <div
                    className={
                        hasVariables
                            ? 'hidden @max-6xl/dashboard-filters:block'
                            : 'hidden @max-4xl/dashboard-filters:block'
                    }
                >
                    <DashboardFiltersMenu showDateFilter={showDateFilter} includeDateAndVariables={false} />
                </div>
            </div>
            <div className="hidden @max-md/dashboard-filters:block">
                <DashboardFiltersMenu showDateFilter={showDateFilter} includeDateAndVariables />
            </div>
            <DashboardEditBarAdvancedFilters showCompareFilter={showDateFilter} />
            {controlsEnabled && (
                <DashboardControlSlot
                    control="metricVariables"
                    hasValue={(effectiveEditBarFilters.metricVariables?.length ?? 0) > 0}
                >
                    <div className="flex min-h-[30px] flex-wrap items-end gap-1 border-l border-primary pl-2">
                        <DashboardMetricVariables />
                    </div>
                </DashboardControlSlot>
            )}
            {showSaveActions && <QuillDashboardUnsavedChangesActions />}
            <DashboardActiveFilterChips
                showDateFilter={showDateFilter}
                className="hidden basis-full @max-md/dashboard-filters:flex"
            />
        </div>
    )
}
