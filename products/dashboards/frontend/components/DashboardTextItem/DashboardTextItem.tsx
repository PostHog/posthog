import { useActions, useValues } from 'kea'
import React from 'react'

import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { textCardConverter } from 'lib/components/Cards/TextCard/textCardMarkdown'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { DashboardPlacement, DashboardTile, DashboardType } from '~/types'

import { DashboardImageTile } from '../ImageTile/DashboardImageTile'
import { getImageOnlyTextCardImage } from '../ImageTile/imageTileUtils'
import { dashboardTextItemLogic } from './dashboardTextItemLogic'

type BaseTextCardProps = React.ComponentProps<typeof TextCard>

interface DashboardTextItemProps extends Omit<
    BaseTextCardProps,
    'textTile' | 'placement' | 'moreButtonOverlay' | 'showAgentContext'
> {
    tile: DashboardTile
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
    const tileType = image ? 'image' : 'text'
    const textItemLogic = dashboardTextItemLogic({ tileId: tile.id })
    const { showAgentContext } = useValues(textItemLogic)
    const { toggleAgentContext } = useActions(textItemLogic)
    const canShowAgentContext = !image && !!tile.text?.agent_context?.trim()
    const moreButtonOverlay = (
        <>
            <LemonButton fullWidth onClick={onEdit} data-attr={`edit-${tileType}`}>
                Edit {tileType}
            </LemonButton>

            {canShowAgentContext && (
                <LemonButton
                    fullWidth
                    onClick={toggleAgentContext}
                    sideIcon={<LemonSwitch checked={showAgentContext} size="xsmall" />}
                    aria-pressed={showAgentContext}
                    data-attr="toggle-text-card-agent-context"
                >
                    Agent context
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
            showAgentContext={showAgentContext}
            {...textCardProps}
        />
    )
}

export const DashboardTextItem = React.forwardRef<HTMLDivElement, DashboardTextItemProps>(
    DashboardTextItemInternal
) as typeof DashboardTextItemInternal
