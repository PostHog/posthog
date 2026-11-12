import { useValues } from 'kea'
import React from 'react'

import { IconChevronRight } from '@posthog/icons'

import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import {
    DashboardWidgetPlacementMenus,
    type DashboardWidgetPlacementMenusProps,
} from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import type { TileDisplayOptions } from 'scenes/dashboard/dashboardLogic'

import { DashboardPlacement, DashboardTile, DashboardType } from '~/types'

import { DashboardImageTile } from '../ImageTile/DashboardImageTile'
import { getImageOnlyTextCardImage } from '../ImageTile/imageTileUtils'
import { QuillDashboardTileMenuItems } from '../QuillDashboardTileMenuItems'
import { TextCardDisplayOptions } from './TextCardDisplayOptions'

type BaseTextCardProps = React.ComponentProps<typeof TextCard>

interface DashboardTextItemProps
    extends
        Omit<BaseTextCardProps, 'textTile' | 'placement' | 'moreButtonOverlay'>,
        Pick<DashboardWidgetPlacementMenusProps, 'tileGroupMoveOptions' | 'onMoveToTileGroup'> {
    tile: DashboardTile
    placement: DashboardPlacement
    dashboardId?: number | null
    onEdit: () => void
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onCopyToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onDuplicate: () => void
    onUpdateDisplayOptions?: (displayOptions: TileDisplayOptions) => void
    onRemove?: () => void
    isDraggingRef?: React.RefObject<boolean>
}

function DashboardTextItemInternal(
    {
        tile,
        placement,
        dashboardId,
        onEdit,
        onMoveToDashboard,
        onCopyToDashboard,
        tileGroupMoveOptions,
        onMoveToTileGroup,
        onDuplicate,
        onUpdateDisplayOptions,
        onRemove,
        isDraggingRef,
        ...textCardProps
    }: DashboardTextItemProps,
    ref: React.ForwardedRef<HTMLDivElement>
): JSX.Element {
    const textId = tile.text?.id
    const { copyToDestinations } = useValues(
        dashboardWidgetMenusLogic({
            instanceKey: textId != null ? `text-${textId}` : `text-tile-${tile.id}`,
            dashboardId,
            dashboard_tiles: tile.text?.dashboard_tiles,
        })
    )

    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const image = tile.text ? getImageOnlyTextCardImage(tile.text.body) : null
    const tileType = image ? 'image' : 'text'
    const displayOptions = onUpdateDisplayOptions ? (
        <TextCardDisplayOptions tile={tile} onUpdateDisplayOptions={onUpdateDisplayOptions} />
    ) : null
    const quillMenuItems = todayRailNav ? (
        <QuillDashboardTileMenuItems
            editLabel={`Edit ${tileType}`}
            editDataAttr={`edit-${tileType}`}
            onEdit={onEdit}
            placement={{
                destinations: copyToDestinations,
                onMoveToDashboard,
                onCopyToDashboard,
                tileGroupMoveOptions,
                onMoveToTileGroup,
            }}
            onDuplicate={onDuplicate}
            duplicateDataAttr={`duplicate-${tileType}-from-dashboard`}
            onRemove={onRemove}
            removeDataAttr={`remove-${tileType}-tile-from-dashboard`}
            displayOptions={displayOptions}
        />
    ) : undefined
    const moreButtonOverlay = (
        <>
            <LemonButton fullWidth onClick={onEdit} data-attr={`edit-${tileType}`}>
                Edit {tileType}
            </LemonButton>
            {displayOptions && (
                <LemonDropdown
                    overlay={<div className="w-60 px-2 py-1">{displayOptions}</div>}
                    closeOnClickInside={false}
                    placement="right-start"
                    fallbackPlacements={['left-start']}
                >
                    <LemonButton
                        fullWidth
                        sideIcon={<IconChevronRight className="size-3" />}
                        data-attr="dashboard-tile-display-options"
                    >
                        Display options
                    </LemonButton>
                </LemonDropdown>
            )}

            <DashboardWidgetPlacementMenus
                placementDestinations={copyToDestinations}
                onMoveToDashboard={onMoveToDashboard}
                onCopyToDashboard={onCopyToDashboard}
                tileGroupMoveOptions={tileGroupMoveOptions}
                onMoveToTileGroup={onMoveToTileGroup}
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
                quillMenuItems={quillMenuItems}
                isDraggingRef={isDraggingRef}
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
            quillMenuItems={quillMenuItems}
            {...textCardProps}
        />
    )
}

export const DashboardTextItem = React.forwardRef<HTMLDivElement, DashboardTextItemProps>(
    DashboardTextItemInternal
) as typeof DashboardTextItemInternal
