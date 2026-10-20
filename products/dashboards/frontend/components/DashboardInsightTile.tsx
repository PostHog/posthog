import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions } from 'kea'
import { forwardRef, memo, useMemo, useState } from 'react'
import type { HTMLAttributes, ReactNode } from 'react'
import { useInView } from 'react-intersection-observer'

import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { InsightCard, InsightCardProps } from 'lib/components/Cards/InsightCard/InsightCard'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { insightsModel } from '~/models/insightsModel'
import type { DashboardTile, InsightModel } from '~/types'
import { DashboardPlacement } from '~/types'

type DashboardInsightTileProps = InsightCardProps &
    Pick<HTMLAttributes<HTMLDivElement>, 'onMouseDown' | 'onMouseUp' | 'onTouchStart' | 'onTouchEnd'> & {
        tile: DashboardTile
        decorations: ReactNode
    }

const MemoizedInsightCard = memo(InsightCard)

export const DashboardInsightTile = forwardRef<HTMLDivElement, DashboardInsightTileProps>(function DashboardInsightTile(
    {
        className,
        style,
        children,
        decorations,
        showResizeHandles,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        onMouseDown,
        onMouseUp,
        onTouchStart,
        onTouchEnd,
        ...cardProps
    },
    ref
): JSX.Element {
    const { updateTileColor, toggleTileDescription, duplicateTile, refreshDashboardItem, setTileOverride } =
        useActions(dashboardLogic)
    const { renameInsight } = useActions(insightsModel)
    const { tile, insight } = cardProps
    const [keepMountedForOverlay, setKeepMountedForOverlay] = useState(false)
    const exportPlacement = cardProps.placement === DashboardPlacement.Export
    const { ref: visibilityRef, inView } = useInView({
        rootMargin: '500px',
        triggerOnce: true,
        initialInView: exportPlacement,
        skip: exportPlacement,
    })
    const mergedRefs = useMergeRefs([ref, visibilityRef])
    const sharedView = isSharedView()
    const tileActions = useMemo(() => {
        const refresh = (updatedInsight?: InsightModel): void => {
            refreshDashboardItem({ tile: updatedInsight ? { ...tile, insight: updatedInsight } : tile })
        }
        return {
            updateColor: (color: DashboardTile['color']): void => updateTileColor(tile.id, color),
            toggleShowDescription: (): void => toggleTileDescription(tile.id),
            duplicate: (): void => duplicateTile(tile),
            rename: (): void => renameInsight(insight),
            setOverride: (): void => setTileOverride(tile),
            refresh: sharedView ? undefined : (): void => refresh(),
            refreshAfterDisplayOptionsChange: sharedView ? undefined : refresh,
        }
    }, [
        tile,
        insight,
        sharedView,
        updateTileColor,
        toggleTileDescription,
        duplicateTile,
        refreshDashboardItem,
        setTileOverride,
        renameInsight,
    ])
    const gridClasses = className?.split(' ') ?? []
    const interactionActive = gridClasses.includes('resizing') || gridClasses.includes('react-draggable-dragging')
    const shouldMountCard = inView || exportPlacement || interactionActive || keepMountedForOverlay

    return (
        <div
            ref={mergedRefs}
            className={clsx('dashboard-insight-tile DashboardTileCard', className)}
            style={style}
            onMouseDown={onMouseDown}
            onMouseUp={onMouseUp}
            onTouchStart={onTouchStart}
            onTouchEnd={onTouchEnd}
        >
            {shouldMountCard ? (
                <MemoizedInsightCard
                    {...cardProps}
                    {...tileActions}
                    keepMountedDuringInteraction={interactionActive}
                    onOverlayVisibilityChange={setKeepMountedForOverlay}
                    renderVizWhenMounted
                >
                    {decorations}
                </MemoizedInsightCard>
            ) : (
                <div className="dashboard-insight-tile__placeholder" aria-hidden="true">
                    <LemonSkeleton className="h-3 w-2/5" active={false} />
                    <LemonSkeleton className="min-h-0 w-full flex-1" active={false} />
                </div>
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {(canEnterEditModeFromEdge || showResizeHandles) && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {children}
        </div>
    )
})
