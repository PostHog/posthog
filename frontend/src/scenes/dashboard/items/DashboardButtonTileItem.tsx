import { useValues } from 'kea'
import React from 'react'

import { ButtonTileCard } from 'lib/components/Cards/ButtonTileCard/ButtonTileCard'
import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import type { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

type BaseButtonTileCardProps = React.ComponentProps<typeof ButtonTileCard>

interface DashboardButtonTileItemProps extends Omit<
    BaseButtonTileCardProps,
    'buttonTile' | 'placement' | 'moreButtonOverlay'
> {
    tile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    dashboardId?: number | null
    onEdit: () => void
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onDuplicate: () => void
    onRemove?: () => void
}

function DashboardButtonTileItemInternal(
    {
        tile,
        placement,
        dashboardId,
        onEdit,
        onMoveToDashboard,
        onDuplicate,
        onRemove,
        ...buttonTileCardProps
    }: DashboardButtonTileItemProps,
    ref: React.ForwardedRef<HTMLDivElement>
): JSX.Element {
    const buttonId = tile.button_tile?.id
    const { copyToDestinations } = useValues(
        dashboardWidgetMenusLogic({
            instanceKey: buttonId != null ? `button-${buttonId}` : `button-tile-${tile.id}`,
            dashboardId,
            dashboards: undefined,
            dashboard_tiles: tile.button_tile?.dashboard_tiles,
        })
    )

    return (
        <ButtonTileCard
            ref={ref}
            buttonTile={tile}
            placement={placement}
            moreButtonOverlay={
                <>
                    <LemonButton fullWidth onClick={onEdit} data-attr="edit-button-tile">
                        Edit button
                    </LemonButton>

                    <DashboardWidgetPlacementMenus
                        placementDestinations={copyToDestinations}
                        onMoveToDashboard={onMoveToDashboard}
                    />

                    <LemonButton onClick={onDuplicate} fullWidth data-attr="duplicate-button-tile-from-dashboard">
                        Duplicate
                    </LemonButton>
                    <LemonDivider />
                    {onRemove && (
                        <LemonButton
                            status="danger"
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Remove button from dashboard',
                                    description: 'Are you sure you want to remove this button from the dashboard?',
                                    primaryButton: {
                                        children: 'Remove from dashboard',
                                        status: 'danger',
                                        onClick: () => onRemove(),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }
                            fullWidth
                            data-attr="remove-button-tile-from-dashboard"
                        >
                            Delete
                        </LemonButton>
                    )}
                </>
            }
            {...buttonTileCardProps}
        />
    )
}

export const DashboardButtonTileItem = React.forwardRef<HTMLDivElement, DashboardButtonTileItemProps>(
    DashboardButtonTileItemInternal
) as typeof DashboardButtonTileItemInternal
