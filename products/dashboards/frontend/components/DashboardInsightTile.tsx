import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions } from 'kea'
import { forwardRef, memo, useEffect, useMemo, useRef, useState } from 'react'
import type { HTMLAttributes, ReactNode } from 'react'
import { useInView } from 'react-intersection-observer'

import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { InsightCard, InsightCardProps } from 'lib/components/Cards/InsightCard/InsightCard'
import { InsightVisualizationSkeleton } from 'lib/components/Cards/InsightCard/InsightVisualizationSkeleton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { insightsModel } from '~/models/insightsModel'
import type { DashboardTile, InsightModel } from '~/types'
import { DashboardPlacement } from '~/types'

import { queueDashboardInsightMount } from './dashboardInsightMountQueue'
import { type MountedTileHandle, trackMountedDashboardTile } from './dashboardMountedTiles'

type DashboardInsightTileProps = InsightCardProps &
    Pick<HTMLAttributes<HTMLDivElement>, 'onMouseDown' | 'onMouseUp' | 'onTouchStart' | 'onTouchEnd'> & {
        tile: DashboardTile
        decorations: ReactNode
    }

const MemoizedInsightCard = memo(InsightCard)
const MOUNT_MARGIN = '500px'
const UNMOUNT_MARGIN = '1500px'

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
    const [cardMounted, setCardMounted] = useState(false)
    const exportPlacement = cardProps.placement === DashboardPlacement.Export
    const { ref: visibilityRef, inView } = useInView({
        rootMargin: MOUNT_MARGIN,
        initialInView: exportPlacement,
        skip: exportPlacement,
    })
    // A wider band than the mount margin, so a tile at the edge does not mount and unmount on small scrolls.
    const { ref: keepRef, inView: withinKeepBand } = useInView({
        rootMargin: UNMOUNT_MARGIN,
        initialInView: true,
        skip: exportPlacement,
    })
    const mergedRefs = useMergeRefs([ref, visibilityRef, keepRef])
    useEffect(() => {
        if (inView && !cardMounted) {
            return queueDashboardInsightMount(() => setCardMounted(true))
        }
    }, [inView, cardMounted])
    const mountedTileRef = useRef<MountedTileHandle | null>(null)
    useEffect(() => {
        if (cardMounted && !exportPlacement) {
            const handle = trackMountedDashboardTile(() => setCardMounted(false))
            mountedTileRef.current = handle
            return () => {
                handle.untrack()
                mountedTileRef.current = null
            }
        }
    }, [cardMounted, exportPlacement])
    useEffect(() => {
        mountedTileRef.current?.setReleasable(!withinKeepBand && !keepMountedForOverlay)
    }, [cardMounted, withinKeepBand, keepMountedForOverlay])
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
    const shouldMountCard = cardMounted || exportPlacement || interactionActive || keepMountedForOverlay

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
                    {inView ? (
                        <InsightVisualizationSkeleton query={insight.query} />
                    ) : (
                        <LemonSkeleton className="min-h-0 w-full flex-1" active={false} />
                    )}
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
