import React from 'react'

import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import type { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

type BaseTextCardProps = React.ComponentProps<typeof TextCard>

interface DashboardTextItemProps extends Omit<BaseTextCardProps, 'textTile' | 'placement' | 'moreButtonOverlay'> {
    tile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    otherDashboards: Pick<DashboardType, 'id' | 'name'>[]
    onEdit: () => void
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onDuplicate: () => void
    onRemove?: () => void
    isDragging?: boolean
}

function DashboardTextItemInternal(
    {
        tile,
        placement,
        otherDashboards,
        onEdit,
        onMoveToDashboard,
        onDuplicate,
        onRemove,
        isDragging,
        ...textCardProps
    }: DashboardTextItemProps,
    ref: React.ForwardedRef<HTMLDivElement>
): JSX.Element {
    return (
        <TextCard
            ref={ref}
            textTile={tile}
            placement={placement}
            moreButtonOverlay={
                <>
                    <LemonButton fullWidth onClick={onEdit} data-attr="edit-text">
                        Edit text
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

                    <LemonButton onClick={onDuplicate} fullWidth data-attr="duplicate-text-from-dashboard">
                        Duplicate
                    </LemonButton>
                    <LemonDivider />
                    {onRemove && (
                        <LemonButton
                            status="danger"
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Remove text from dashboard',
                                    description: 'Are you sure you want to remove this text card from the dashboard?',
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
                            data-attr="remove-text-tile-from-dashboard"
                        >
                            Delete
                        </LemonButton>
                    )}
                </>
            }
            {...textCardProps}
        />
    )
}

export const DashboardTextItem = React.forwardRef<HTMLDivElement, DashboardTextItemProps>(
    DashboardTextItemInternal
) as typeof DashboardTextItemInternal
