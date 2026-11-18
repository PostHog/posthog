import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Suspense, forwardRef, memo, useEffect, useMemo, useRef, useState } from 'react'
import type { HTMLAttributes, ReactNode } from 'react'
import { useInView } from 'react-intersection-observer'

import { Card } from '@posthog/quill'

import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { InsightCard, InsightCardProps } from 'lib/components/Cards/InsightCard/InsightCard'
import { InsightVisualizationSkeleton } from 'lib/components/Cards/InsightCard/InsightVisualizationSkeleton'
import { QuillSurfaceContext } from 'lib/components/QuillSurface/quillSurfaceContext'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { getEffectiveDateOverride } from 'scenes/dashboard/dashboardUtils'
import { dateRangeZoomEnd, hasTimeComponent } from 'scenes/insights/insightVizDataLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { insightsModel } from '~/models/insightsModel'
import { isInsightVizNode, isMetricsQuery } from '~/queries/schema/node-guards'
import type { DashboardTile, InsightModel } from '~/types'
import { DashboardPlacement } from '~/types'

import { cropInsightToZoom } from '../zoomPreview'
import { queueDashboardInsightMount } from './dashboardInsightMountQueue'
import { type MountedTileHandle, trackMountedDashboardTile } from './dashboardMountedTiles'

// Dashboard tiles are always draggable for editors, so InsightCard's edit-mode entry props
// (still used by cross-project dashboards) do not apply here.
type DashboardInsightTileProps = Omit<
    InsightCardProps,
    'canEnterEditModeFromEdge' | 'onEnterEditModeFromEdge' | 'onDragHandleMouseDown'
> &
    Pick<HTMLAttributes<HTMLDivElement>, 'onMouseDown' | 'onMouseUp' | 'onTouchStart' | 'onTouchEnd'> & {
        tile: DashboardTile
        decorations: ReactNode
    }

const MemoizedInsightCard = memo(InsightCard)
const MOUNT_MARGIN = '500px'
const UNMOUNT_MARGIN = '1500px'
const MetricsPanelEditor = lazyWithRetry(() =>
    import('../MetricsPanelEditor').then((m) => ({ default: m.MetricsPanelEditor }))
)

export const DashboardInsightTile = forwardRef<HTMLDivElement, DashboardInsightTileProps>(function DashboardInsightTile(
    {
        className,
        style,
        children,
        decorations,
        showResizeHandles,
        onMouseDown,
        onMouseUp,
        onTouchStart,
        onTouchEnd,
        ...cardProps
    },
    ref
): JSX.Element {
    const {
        updateTileColor,
        toggleTileDescription,
        duplicateTile,
        refreshDashboardItem,
        setTileOverride,
        zoomDateRange,
        loadDashboard,
    } = useActions(dashboardLogic)
    const { zoomPreview, currentTeamId } = useValues(dashboardLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { renameInsight } = useActions(insightsModel)
    const { tile, insight } = cardProps
    const [keepMountedForOverlay, setKeepMountedForOverlay] = useState(false)
    const [cardMounted, setCardMounted] = useState(false)
    const [editingMetrics, setEditingMetrics] = useState(false)
    const metricsBuilderEnabled = useFeatureFlag('METRICS_INSIGHT_BUILDER')
    const canEditMetricsHere =
        metricsBuilderEnabled &&
        cardProps.canEditDashboard &&
        cardProps.placement === DashboardPlacement.Dashboard &&
        isMetricsQuery(insight.query)
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
        mountedTileRef.current?.setReleasable(!withinKeepBand && !keepMountedForOverlay && !editingMetrics)
    }, [cardMounted, withinKeepBand, keepMountedForOverlay, editingMetrics])
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
    const zoomInterval =
        isInsightVizNode(insight.query) && 'interval' in insight.query.source
            ? insight.query.source.interval
            : undefined
    const zoomQueryKind = isInsightVizNode(insight.query) ? insight.query.source.kind : undefined
    const overrides = tile.filters_overrides
    const editorDates = getEffectiveDateOverride(insight.filter_override_context, cardProps.filtersOverride, overrides)
    // A tile with its own dates ignores the dashboard's, so zooming it would change every tile but this one.
    const tileOwnsDates = !!(overrides?.date_from || overrides?.date_to || overrides?.ignoreDashboardFilters)
    const onDateRangeZoom = useMemo(
        () =>
            cardProps.placement === DashboardPlacement.Dashboard && !tileOwnsDates
                ? (dateFrom: string, dateTo: string): void =>
                      zoomDateRange(
                          dateFrom,
                          dateRangeZoomEnd(dateTo, zoomInterval),
                          hasTimeComponent(dateFrom),
                          zoomQueryKind
                      )
                : undefined,
        [cardProps.placement, tileOwnsDates, zoomInterval, zoomQueryKind, zoomDateRange]
    )
    const displayedInsight = useMemo(() => {
        const dateRange = isInsightVizNode(insight.query) ? insight.query.source.dateRange : undefined
        const resultsMatchZoom =
            dateRange?.date_from === zoomPreview?.dateFrom && dateRange?.date_to === zoomPreview?.dateTo
        return zoomPreview && !tileOwnsDates && !resultsMatchZoom ? cropInsightToZoom(insight, zoomPreview) : insight
    }, [insight, zoomPreview, tileOwnsDates])
    const gridClasses = className?.split(' ') ?? []
    const interactionActive = gridClasses.includes('resizing') || gridClasses.includes('react-draggable-dragging')
    const shouldMountCard = cardMounted || exportPlacement || interactionActive || keepMountedForOverlay

    const shellProps = {
        ref: mergedRefs,
        className: clsx('dashboard-insight-tile DashboardTileCard', todayRailNav && 'overflow-visible pt-0', className),
        style,
        onMouseDown,
        onMouseUp,
        onTouchStart,
        onTouchEnd,
    }
    const tileContent = (
        <>
            {shouldMountCard ? (
                <QuillSurfaceContext.Provider value={todayRailNav}>
                    <MemoizedInsightCard
                        {...cardProps}
                        {...tileActions}
                        insight={displayedInsight}
                        onDateRangeZoom={onDateRangeZoom}
                        keepMountedDuringInteraction={interactionActive}
                        onOverlayVisibilityChange={setKeepMountedForOverlay}
                        renderVizWhenMounted
                        editInDashboard={canEditMetricsHere ? () => setEditingMetrics(true) : undefined}
                    >
                        {decorations}
                    </MemoizedInsightCard>
                </QuillSurfaceContext.Provider>
            ) : (
                <div
                    className={clsx(
                        'dashboard-insight-tile__placeholder',
                        todayRailNav && 'dashboard-insight-tile__placeholder--quill'
                    )}
                    data-not-quill
                    aria-hidden="true"
                >
                    <LemonSkeleton className="h-3 w-2/5" active={false} />
                    {inView ? (
                        <InsightVisualizationSkeleton query={insight.query} />
                    ) : (
                        <LemonSkeleton className="min-h-0 w-full flex-1" active={false} />
                    )}
                </div>
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {children}
            {editingMetrics && currentTeamId && (
                <Suspense fallback={<Spinner />}>
                    <MetricsPanelEditor
                        projectId={currentTeamId}
                        insightId={insight.id}
                        dashboardId={cardProps.dashboardId}
                        filtersOverride={{
                            ...(overrides?.ignoreDashboardFilters
                                ? {}
                                : { metricVariables: cardProps.filtersOverride?.metricVariables }),
                            date_from: editorDates.dateFromOverride,
                            date_to: editorDates.dateToOverride,
                        }}
                        onClose={() => setEditingMetrics(false)}
                        onSaved={() => loadDashboard({ action: DashboardLoadAction.Update })}
                    />
                </Suspense>
            )}
        </>
    )

    return todayRailNav ? (
        <Card flush {...shellProps}>
            {tileContent}
        </Card>
    ) : (
        <div {...shellProps}>{tileContent}</div>
    )
})
