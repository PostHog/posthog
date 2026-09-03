import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'

import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { textCardConverter } from 'lib/components/Cards/TextCard/textCardMarkdown'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import { DashboardImageTile } from '../ImageTile/DashboardImageTile'
import { getImageOnlyTextCardImage } from '../ImageTile/imageTileUtils'

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
        className,
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

    const image = tile.text ? getImageOnlyTextCardImage(textCardConverter, tile.text.body) : null
    const isSeparator = tile.text?.tile_type === 'divider'
    let tileType = 'text'
    if (image) {
        tileType = 'image'
    }
    const moreButtonOverlay = (
        <>
            {!isSeparator && (
                <LemonButton fullWidth onClick={onEdit} data-attr={`edit-${tileType}`}>
                    Edit {tileType}
                </LemonButton>
            )}

            <DashboardWidgetPlacementMenus
                placementDestinations={copyToDestinations}
                onMoveToDashboard={onMoveToDashboard}
                onCopyToDashboard={onCopyToDashboard}
            />

            <LemonButton onClick={onDuplicate} fullWidth data-attr={`duplicate-${tileType}-from-dashboard`}>
                Duplicate
            </LemonButton>
            <LemonDivider />
            {onRemove && (
                <LemonButton
                    status="danger"
                    onClick={() => onRemove()}
                    fullWidth
                    data-attr={`remove-${tileType}-tile-from-dashboard`}
                >
                    Delete
                </LemonButton>
            )}
        </>
    )

    if (image) {
        return (
            <DashboardImageTile
                ref={ref}
                tile={tile}
                image={image}
                placement={placement}
                moreButtonOverlay={moreButtonOverlay}
                className={className}
                {...textCardProps}
            />
        )
    }

    return (
        <TextCard
            ref={ref}
            textTile={tile}
            placement={placement}
            moreButtonOverlay={moreButtonOverlay}
            className={clsx(isSeparator && 'DashboardDividerTile', className)}
            {...textCardProps}
        />
    )
}

export const DashboardTextItem = React.forwardRef<HTMLDivElement, DashboardTextItemProps>(
    DashboardTextItemInternal
) as typeof DashboardTextItemInternal
