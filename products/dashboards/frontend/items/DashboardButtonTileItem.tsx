import { useValues } from 'kea'
import React from 'react'

import { IconChevronRight } from '@posthog/icons'

import { ButtonTileCard } from 'lib/components/Cards/ButtonTileCard/ButtonTileCard'
import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import {
    DashboardWidgetPlacementMenus,
    type DashboardWidgetPlacementMenusProps,
} from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import type { TileDisplayOptions } from 'scenes/dashboard/dashboardLogic'

import type { DashboardPlacement, DashboardTile, DashboardType } from '~/types'

import { TextCardDisplayOptions } from '../components/DashboardTextItem/TextCardDisplayOptions'
import { QuillDashboardTileMenuItems } from '../components/QuillDashboardTileMenuItems'

type BaseButtonTileCardProps = React.ComponentProps<typeof ButtonTileCard>

interface DashboardButtonTileItemProps
    extends
        Omit<BaseButtonTileCardProps, 'buttonTile' | 'placement' | 'moreButtonOverlay'>,
        Pick<DashboardWidgetPlacementMenusProps, 'tileGroupMoveOptions' | 'onMoveToTileGroup'> {
    tile: DashboardTile
    placement: DashboardPlacement
    dashboardId?: number | null
    onEdit: () => void
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onDuplicate: () => void
    onUpdateDisplayOptions?: (displayOptions: TileDisplayOptions) => void
    displayOptionsSaving?: boolean
    onRemove?: () => void
}

function DashboardButtonTileItemInternal(
    {
        tile,
        placement,
        dashboardId,
        onEdit,
        onMoveToDashboard,
        tileGroupMoveOptions,
        onMoveToTileGroup,
        onDuplicate,
        onUpdateDisplayOptions,
        displayOptionsSaving,
        onRemove,
        ...buttonTileCardProps
    }: DashboardButtonTileItemProps,
    ref: React.ForwardedRef<HTMLDivElement>
): JSX.Element {
    const buttonId = tile.button_tile?.id
    const dashboardWidgetMenusLogicProps = {
        instanceKey: buttonId != null ? `button-${buttonId}` : `button-tile-${tile.id}`,
        dashboardId,
        dashboard_tiles: tile.button_tile?.dashboard_tiles,
    }
    const { copyToDestinations } = useValues(dashboardWidgetMenusLogic(dashboardWidgetMenusLogicProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const displayOptions = onUpdateDisplayOptions ? (
        <TextCardDisplayOptions
            tile={tile}
            onUpdateDisplayOptions={onUpdateDisplayOptions}
            saving={displayOptionsSaving}
            dataAttr="button-tile-menu-transparent-background"
        />
    ) : null

    return (
        <ButtonTileCard
            ref={ref}
            buttonTile={tile}
            placement={placement}
            quillMenuItems={
                todayRailNav ? (
                    <QuillDashboardTileMenuItems
                        editLabel="Edit button"
                        editDataAttr="edit-button-tile"
                        onEdit={onEdit}
                        placement={{
                            destinations: copyToDestinations,
                            onMoveToDashboard,
                            tileGroupMoveOptions,
                            onMoveToTileGroup,
                        }}
                        onDuplicate={onDuplicate}
                        duplicateDataAttr="duplicate-button-tile-from-dashboard"
                        onRemove={onRemove}
                        removeDataAttr="remove-button-tile-from-dashboard"
                        displayOptions={displayOptions}
                    />
                ) : undefined
            }
            moreButtonOverlay={
                <>
                    <LemonButton fullWidth onClick={onEdit} data-attr="edit-button-tile">
                        Edit button
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
                        tileGroupMoveOptions={tileGroupMoveOptions}
                        onMoveToTileGroup={onMoveToTileGroup}
                    />

                    <LemonButton onClick={onDuplicate} fullWidth data-attr="duplicate-button-tile-from-dashboard">
                        Duplicate
                    </LemonButton>
                    <LemonDivider />
                    {onRemove && (
                        <LemonButton
                            status="danger"
                            onClick={() => onRemove()}
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
