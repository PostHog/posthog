import { useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { Popover } from 'lib/lemon-ui/Popover'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'

import { DashboardDateFilter } from './DashboardDateFilter'
import { DashboardScopeFilters } from './DashboardScopeFilters'

interface DashboardFiltersMenuProps {
    showDateFilter: boolean
    /** Also moves the variables and the date range into the menu, for a bar too narrow to show them. */
    includeDateAndVariables: boolean
}

/** "Filters" button that holds the filter controls when the dashboard filter bar is too narrow to show them in a row. */
export function DashboardFiltersMenu({
    showDateFilter,
    includeDateAndVariables,
}: DashboardFiltersMenuProps): JSX.Element {
    const { effectiveEditBarFilters } = useValues(dashboardLogic)
    const quillSurface = useQuillSurface()
    const [visible, setVisible] = useState(false)

    const hasDateRange = !!effectiveEditBarFilters.date_from || !!effectiveEditBarFilters.date_to
    // Variables always hold a value and show as chips next to the bar, so they don't count towards the badge.
    const activeCount =
        (includeDateAndVariables && showDateFilter && hasDateRange ? 1 : 0) +
        (showDateFilter && effectiveEditBarFilters.interval != null ? 1 : 0) +
        (effectiveEditBarFilters.properties?.length ?? 0) +
        (effectiveEditBarFilters.breakdown_filter ? 1 : 0)
    const label = activeCount ? `Filters, ${activeCount} active` : 'Filters'

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="bottom-start"
            overlay={
                <div className="flex max-w-120 flex-col items-start gap-2 p-2">
                    {includeDateAndVariables && <VariablesForDashboard />}
                    {includeDateAndVariables && showDateFilter && <DashboardDateFilter />}
                    <DashboardScopeFilters showIntervalFilter={showDateFilter} logicKeySuffix="menu" />
                </div>
            }
        >
            {quillSurface ? (
                <Button
                    variant="outline"
                    aria-label={label}
                    aria-expanded={visible}
                    indicator={activeCount ? 'default' : undefined}
                    onClick={() => setVisible(!visible)}
                    data-attr="dashboard-filters-menu"
                >
                    <IconFilter />
                    Filters
                </Button>
            ) : (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconFilter />}
                    aria-label={label}
                    active={visible}
                    onClick={() => setVisible(!visible)}
                    sideIcon={activeCount ? <LemonBadge.Number count={activeCount} size="small" /> : undefined}
                    data-attr="dashboard-filters-menu"
                >
                    Filters
                </LemonButton>
            )}
        </Popover>
    )
}
