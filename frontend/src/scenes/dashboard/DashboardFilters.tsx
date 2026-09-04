import clsx from 'clsx'
import { useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DashboardMode, DashboardPlacement } from '~/types'

import { DashboardEditBar } from './DashboardEditBar'
import { dashboardLogic } from './dashboardLogic'
import { DashboardReloadAction, LastRefreshText } from './DashboardReloadAction'
import { DashboardUnsavedChangesIndicator } from './DashboardUnsavedChangesIndicator'

interface DashboardFilterBarProps {
    backTo?: { url: string; name: string }
}

export function DashboardFilterBar({ backTo }: DashboardFilterBarProps): JSX.Element {
    const { placement, dashboard, dashboardMode, hasVariables } = useValues(dashboardLogic)
    return (
        <div className="@container/dashboard-filters flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex flex-wrap gap-x-2 gap-y-2 justify-between items-start">
                <div className="flex min-w-0 flex-1 flex-col gap-2 @2xl/dashboard-filters:flex-row @2xl/dashboard-filters:justify-between items-start @4xl/dashboard-filters:items-center">
                    <div className="flex min-w-0 flex-1 flex-wrap gap-4 items-center">
                        {![
                            DashboardPlacement.Public,
                            DashboardPlacement.Export,
                            DashboardPlacement.FeatureFlag,
                            DashboardPlacement.Group,
                            DashboardPlacement.DataOps,
                            DashboardPlacement.Builtin,
                        ].includes(placement) &&
                            dashboard && <DashboardEditBar />}
                        {placement === DashboardPlacement.Dashboard && <DashboardUnsavedChangesIndicator />}
                    </div>
                </div>
                {![DashboardPlacement.Export, DashboardPlacement.Builtin].includes(placement) && (
                    <div
                        className={clsx(
                            'flex flex-col @4xl/dashboard-filters:flex-row items-end @4xl/dashboard-filters:items-center gap-4 dashoard-items-actions',
                            'min-w-0 @max-4xl/dashboard-filters:basis-full @max-4xl/dashboard-filters:w-full @max-4xl/dashboard-filters:ml-0 shrink-0 @4xl/dashboard-filters:ml-auto',
                            {
                                'mt-7': hasVariables,
                            }
                        )}
                    >
                        <div className={`left-item ${placement === DashboardPlacement.Public ? 'text-right' : ''}`}>
                            {[DashboardPlacement.Public].includes(placement) ? (
                                <LastRefreshText />
                            ) : !(dashboardMode === DashboardMode.Edit) ? (
                                <DashboardReloadAction />
                            ) : null}
                        </div>
                        {[
                            DashboardPlacement.FeatureFlag,
                            DashboardPlacement.Group,
                            DashboardPlacement.DataOps,
                        ].includes(placement) &&
                            dashboard?.id && (
                                <LemonMenu
                                    items={[
                                        {
                                            label:
                                                placement === DashboardPlacement.Group
                                                    ? 'Edit dashboard template'
                                                    : 'Edit dashboard',
                                            to: backTo
                                                ? `${urls.dashboard(dashboard.id)}?backUrl=${encodeURIComponent(backTo.url)}&backName=${encodeURIComponent(backTo.name)}`
                                                : urls.dashboard(dashboard.id),
                                        },
                                    ]}
                                    placement="bottom-end"
                                    fallbackPlacements={['bottom-start', 'bottom']}
                                >
                                    <LemonButton size="small" icon={<IconEllipsis className="text-secondary" />} />
                                </LemonMenu>
                            )}
                    </div>
                )}
            </div>
        </div>
    )
}
