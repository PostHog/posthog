import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconPalette } from '@posthog/icons'
import { LemonButton, LemonLabel } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Popover } from 'lib/lemon-ui/Popover'
import { dashboardInsightColorsModalLogic } from 'scenes/dashboard/dashboardInsightColorsModalLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { DashboardPlacement } from '~/types'

/**
 * "…" at the end of the dashboard edit bar, opening a panel for overrides that are too rarely
 * used to earn a spot in the bar itself. Hosts the breakdown color override.
 */
export function DashboardEditBarAdvancedFilters(): JSX.Element | null {
    const { dashboard, placement, canEditDashboard } = useValues(dashboardLogic)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    const hasDashboardColors = useFeatureFlag('PRODUCT_ANALYTICS_DASHBOARD_COLORS')
    const [visible, setVisible] = useState(false)

    // Only the full dashboard scene mounts DashboardInsightColorsModal, so elsewhere the button would no-op.
    const showColors =
        hasDashboardColors && canEditDashboard && !!dashboard && placement === DashboardPlacement.Dashboard
    if (!showColors) {
        return null
    }

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
                </div>
            }
        >
            <LemonButton
                size="small"
                icon={<IconEllipsis />}
                tooltip="Advanced options"
                active={visible}
                onClick={() => setVisible(!visible)}
                data-attr="dashboard-advanced-filters"
            />
        </Popover>
    )
}
