import { useValues } from 'kea'
import React, { useState } from 'react'

import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { TextCardInlineEditor } from 'lib/components/Cards/TextCard/TextCardInlineEditor'
import { isTextCardMarkdownRoundTripSafe } from 'lib/components/Cards/TextCard/textCardMarkdown'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

type BaseTextCardProps = React.ComponentProps<typeof TextCard>

interface DashboardTextItemProps extends Omit<BaseTextCardProps, 'textTile' | 'placement' | 'moreButtonOverlay'> {
    tile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    dashboard?: DashboardType<QueryBasedInsightModel> | null
    dashboardId?: number | null
    canEditDashboard?: boolean
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
        dashboard,
        dashboardId,
        canEditDashboard,
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
    const [isEditingInline, setIsEditingInline] = useState(false)

    // Legacy markdown that can't round-trip through the rich editor still edits via the modal
    const canEditInline = !!dashboard && isTextCardMarkdownRoundTripSafe(tile.text?.body)
    // Only editors get the inline affordance, mirroring insight cards (InsightMeta) and drag-to-edit
    const startEditing = canEditDashboard
        ? (): void => (canEditInline ? setIsEditingInline(true) : onEdit())
        : undefined

    return (
        <TextCard
            ref={ref}
            textTile={tile}
            placement={placement}
            onStartInlineEdit={startEditing}
            editingContent={
                isEditingInline && dashboard ? (
                    <TextCardInlineEditor dashboard={dashboard} tile={tile} onClose={() => setIsEditingInline(false)} />
                ) : undefined
            }
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
                            onClick={() => onRemove()}
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
