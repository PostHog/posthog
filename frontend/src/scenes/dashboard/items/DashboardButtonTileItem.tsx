import React from 'react'

import { ButtonTileCard } from 'lib/components/Cards/ButtonTileCard/ButtonTileCard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import type { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

type BaseButtonTileCardProps = React.ComponentProps<typeof ButtonTileCard>

interface DashboardButtonTileItemProps extends Omit<
    BaseButtonTileCardProps,
    'buttonTile' | 'placement' | 'moreButtonOverlay'
> {
    tile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    otherDashboards: Pick<DashboardType, 'id' | 'name'>[]
    onEdit: () => void
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onDuplicate: () => void
    onRemove?: () => void
}

function DashboardButtonTileItemInternal(
    {
        tile,
        placement,
        otherDashboards,
        onEdit,
        onMoveToDashboard,
        onDuplicate,
        onRemove,
        ...buttonTileCardProps
    }: DashboardButtonTileItemProps,
    ref: React.ForwardedRef<HTMLDivElement>
): JSX.Element {
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

                    {onMoveToDashboard && (
                        <LemonMenu
                            placement="right-start"
                            fallbackPlacements={['left-start']}
                            closeParentPopoverOnClickInside
                            items={
                                otherDashboards.length
                                    ? otherDashboards.map((otherDashboard) => ({
                                          label: otherDashboard.name || <i>Untitled</i>,
                                          onClick: () => onMoveToDashboard(otherDashboard),
                                      }))
                                    : [
                                          {
                                              label: 'No other dashboards',
                                              disabledReason: 'No other dashboards',
                                          },
                                      ]
                            }
                        >
                            <LemonButton
                                fullWidth
                                disabledReason={otherDashboards.length ? undefined : 'No other dashboards'}
                            >
                                Move to
                            </LemonButton>
                        </LemonMenu>
                    )}

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
