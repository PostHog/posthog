import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType, DashboardPlacement, DashboardTile, InsightColor, QueryBasedInsightModel } from '~/types'

const RIBBON_COLOR_CLASSES: Record<InsightColor, string> = {
    [InsightColor.White]: 'border-l-4 border-l-white',
    [InsightColor.Black]: 'border-l-4 border-l-black',
    [InsightColor.Blue]: 'border-l-4 border-l-blue',
    [InsightColor.Green]: 'border-l-4 border-l-green',
    [InsightColor.Purple]: 'border-l-4 border-l-purple',
}

interface DashboardTileMetaProps {
    insight: QueryBasedInsightModel
    tile?: DashboardTile<QueryBasedInsightModel>
    dashboardId?: number
    ribbonColor?: InsightColor | null
    loading?: boolean
    loadingQueued?: boolean
    apiErrored?: boolean
    showEditingControls?: boolean
    refresh?: () => void
    refreshEnabled?: boolean
    duplicate?: () => void
    removeFromDashboard?: () => void
    moveToDashboard?: (dashboard: DashboardBasicType) => void
    placement?: DashboardPlacement | 'SavedInsightGrid'
}

export function DashboardTileMeta({
    insight,
    ribbonColor,
    loading,
    loadingQueued,
    apiErrored,
    showEditingControls,
    refresh,
    refreshEnabled,
    duplicate,
    removeFromDashboard,
    moveToDashboard,
    dashboardId,
}: DashboardTileMetaProps): JSX.Element {
    const { push } = useActions(router)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards = nameSortedDashboards.filter((d) => d.id !== dashboardId)

    return (
        <div
            className={clsx(
                'CardMeta px-2 py-1.5 flex items-center gap-1 border-b cursor-move',
                ribbonColor && RIBBON_COLOR_CLASSES[ribbonColor]
            )}
        >
            <LemonButton
                className="flex-1 min-w-0"
                type="tertiary"
                size="small"
                noPadding
                onClick={() => push(urls.insightView(insight.short_id))}
                data-attr="dashboard-tile-title"
            >
                <span className="truncate font-semibold text-sm">
                    {insight.name || insight.derived_name || 'Untitled'}
                </span>
            </LemonButton>

            {(loading || loadingQueued) && <Spinner className="text-lg" />}
            {apiErrored && <span className="text-danger text-xs">Error</span>}

            {showEditingControls && (
                <LemonButtonWithDropdown
                    dropdown={{
                        overlay: (
                            <>
                                {refresh && (
                                    <LemonButton
                                        fullWidth
                                        onClick={refresh}
                                        disabledReason={!refreshEnabled ? 'Refreshing...' : undefined}
                                    >
                                        Refresh
                                    </LemonButton>
                                )}
                                {duplicate && (
                                    <LemonButton fullWidth onClick={duplicate}>
                                        Duplicate
                                    </LemonButton>
                                )}
                                {moveToDashboard && otherDashboards.length > 0 && (
                                    <LemonButtonWithDropdown
                                        dropdown={{
                                            overlay: otherDashboards.map((d) => (
                                                <LemonButton key={d.id} onClick={() => moveToDashboard(d)} fullWidth>
                                                    {d.name || <i>Untitled</i>}
                                                </LemonButton>
                                            )),
                                            placement: 'right-start',
                                            fallbackPlacements: ['left-start'],
                                            actionable: true,
                                            closeParentPopoverOnClickInside: true,
                                        }}
                                        fullWidth
                                    >
                                        Move to
                                    </LemonButtonWithDropdown>
                                )}
                                {removeFromDashboard && (
                                    <>
                                        <LemonDivider />
                                        <LemonButton status="danger" onClick={removeFromDashboard} fullWidth>
                                            Remove from dashboard
                                        </LemonButton>
                                    </>
                                )}
                            </>
                        ),
                        placement: 'bottom-end',
                    }}
                    size="small"
                    type="tertiary"
                    icon={<IconEllipsis />}
                    data-attr="dashboard-tile-more"
                />
            )}
        </div>
    )
}
