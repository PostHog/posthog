import { useValues } from 'kea'
import React from 'react'

import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

type BaseTextCardProps = React.ComponentProps<typeof TextCard>

interface DashboardTextItemProps extends Omit<BaseTextCardProps, 'textTile' | 'placement' | 'moreButtonOverlay'> {
    tile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    dashboardId?: number | null
    onEdit: () => void
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onCopyToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onDuplicate: () => void
    onRemove?: () => void
    isDragging?: boolean
}

function DashboardTextItemInternal(
    {
        tile,
        placement,
        dashboardId,
        onEdit,
        onMoveToDashboard,
        onCopyToDashboard,
        onDuplicate,
        onRemove,
        isDragging,
        ...textCardProps
    }: DashboardTextItemProps,
    ref: React.ForwardedRef<HTMLDivElement>
): JSX.Element {
    const textId = tile.text?.id
    const { copyToDestinations } = useValues(
        dashboardWidgetMenusLogic({
            instanceKey: textId != null ? `text-${textId}` : `text-tile-${tile.id}`,
            dashboardId,
            dashboards: undefined,
            dashboard_tiles: tile.text?.dashboard_tiles,
        })
    )

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

                    <DashboardWidgetPlacementMenus
                        placementDestinations={copyToDestinations}
                        onMoveToDashboard={onMoveToDashboard}
                        onCopyToDashboard={onCopyToDashboard}
                    />

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
