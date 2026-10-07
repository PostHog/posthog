import clsx from 'clsx'
import React, { useEffect, useState } from 'react'

import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { CardMeta, Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdge, EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { InsightCard, type InsightCardProps } from 'lib/components/Cards/InsightCard/InsightCard'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { InsightErrorState } from 'scenes/insights/EmptyStates/EmptyStates'

import { DashboardPlacement, type DashboardTile, type InsightColor, type InsightModel } from '~/types'

import type { CrossProjectDashboardFilters } from './crossProjectDashboardLogic'
import type { TileUnavailableReason } from './crossProjectTileFetch'
import { fetchCrossProjectTile } from './crossProjectTileFetch'
import { mergeTileFilters } from './crossProjectTileFilters'
import type { CrossProjectDashboardTileApi } from './generated/api.schemas'

// The card forwards refs, but its export's type hides that, and the grid needs the ref to drag the card.
const GridInsightCard = InsightCard as unknown as React.ForwardRefExoticComponent<
    InsightCardProps & React.RefAttributes<HTMLDivElement>
>

const UNAVAILABLE_COPY: Record<TileUnavailableReason, string> = {
    'no-access': 'You do not have access to this insight. Ask an admin of its project for access.',
    'not-found': 'This insight no longer exists. Remove the tile or point it at another insight.',
    failed: 'This tile could not load. Refresh the page to try again.',
}

/** The card reads only `id`, `filters_overrides` and `show_description`, and our id is a UUID where `DashboardTile` declares a number. */
function asCardTile(tile: CrossProjectDashboardTileApi): DashboardTile {
    return {
        id: tile.id,
        // The card's links carry any override as a URL parameter, an empty one included.
        filters_overrides: Object.keys(tile.filters_overrides ?? {}).length > 0 ? tile.filters_overrides : null,
        show_description: null,
        color: tile.color,
        layouts: tile.layouts,
    } as unknown as DashboardTile
}

/** react-grid-layout injects style, className, mouse handlers, ref and resize handles into its direct child. */
export interface CrossProjectTileProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    tile: CrossProjectDashboardTileApi
    projectName?: string
    projectTimezone?: string
    /** True when the dashboard's tiles do not all share one time zone. */
    showTimezone?: boolean
    missingPropertyKeys?: string[]
    dashboardFilters?: CrossProjectDashboardFilters
    isResizing?: boolean
    canEnterEditModeFromEdge?: boolean
    onEnterEditModeFromEdge?: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    onSetColor?: (color: InsightColor | null) => void
    onSetOverride?: () => void
    onRemove?: () => void
}

function CrossProjectTileInternal(
    {
        tile,
        projectName,
        projectTimezone,
        showTimezone,
        missingPropertyKeys,
        dashboardFilters,
        isResizing,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        onDragHandleMouseDown,
        onSetColor,
        onSetOverride,
        onRemove,
        showResizeHandles,
        className,
        children,
        ...divProps
    }: CrossProjectTileProps,
    ref: React.ForwardedRef<HTMLDivElement>
): JSX.Element {
    const [insight, setInsight] = useState<InsightModel | null>(null)
    const [unavailable, setUnavailable] = useState<TileUnavailableReason | null>(null)
    const [loading, setLoading] = useState(true)

    const filters = mergeTileFilters(dashboardFilters, tile.filters_overrides as CrossProjectDashboardFilters)
    // Compared by value, so a re-render that rebuilds the filters object does not refetch the tile.
    const filtersKey = JSON.stringify(filters)

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        const parsed = filtersKey === '{}' ? undefined : JSON.parse(filtersKey)
        void fetchCrossProjectTile(tile.project_id, tile.insight_id, parsed).then((result) => {
            if (cancelled) {
                return
            }
            setInsight(result.insight)
            setUnavailable(result.unavailable)
            setLoading(false)
        })
        return () => {
            cancelled = true
        }
    }, [tile.project_id, tile.insight_id, filtersKey])

    // Each tile answers from one project, so the project has to stay visible: without it two
    // tiles side by side read as one combined number. An unreachable insight gets no label,
    // because the reader is not entitled to the project's name either.
    const projectHeading =
        insight && projectName ? (
            <span className="flex items-center gap-1 min-w-0" data-attr="cross-project-tile-meta">
                <span className="truncate">{projectName}</span>
                {showTimezone && projectTimezone ? (
                    <Tooltip
                        title={`This project reports in ${projectTimezone}. Tiles in other time zones cover different day boundaries.`}
                    >
                        <LemonTag type="muted" size="small">
                            {projectTimezone}
                        </LemonTag>
                    </Tooltip>
                ) : null}
                {missingPropertyKeys?.length ? (
                    <Tooltip
                        title={`This project has never recorded ${missingPropertyKeys.join(', ')}, so the filter matches nothing here.`}
                    >
                        <LemonTag type="warning" size="small" data-attr="cross-project-tile-missing-key">
                            Filter not in this project
                        </LemonTag>
                    </Tooltip>
                ) : null}
            </span>
        ) : null

    if (insight && !unavailable && !loading) {
        return (
            <GridInsightCard
                ref={ref}
                // The card spreads the grid's mouse handlers onto its root, but its props type does not declare them.
                {...(divProps as Pick<InsightCardProps, 'style'>)}
                className={className}
                insight={insight}
                tile={asCardTile(tile)}
                projectId={tile.project_id}
                contextHeading={projectHeading}
                ribbonColor={tile.color as InsightColor | null}
                updateColor={onSetColor ? (color) => onSetColor(color ?? null) : undefined}
                setOverride={onSetOverride}
                removeFromDashboard={onRemove}
                showResizeHandles={showResizeHandles}
                isResizing={isResizing}
                canEnterEditModeFromEdge={canEnterEditModeFromEdge}
                onEnterEditModeFromEdge={onEnterEditModeFromEdge}
                onDragHandleMouseDown={onDragHandleMouseDown}
                placement={DashboardPlacement.Dashboard}
            >
                {children}
            </GridInsightCard>
        )
    }

    // Loading and unavailable tiles keep the card's shell, so they drag and resize like the rest.
    return (
        <div
            className={clsx('DashboardTileCard InsightCard border', className)}
            data-attr={loading ? 'cross-project-tile-loading' : 'cross-project-tile-unavailable'}
            ref={ref}
            {...divProps}
        >
            <CardMeta
                showEditingControls={!!onRemove}
                onMouseDown={onDragHandleMouseDown}
                moreButtons={
                    onRemove ? (
                        <LemonButton status="danger" onClick={onRemove} fullWidth>
                            Remove from dashboard
                        </LemonButton>
                    ) : undefined
                }
            />
            {loading ? (
                <LemonSkeleton className="flex-1 m-2" />
            ) : (
                <InsightErrorState title={UNAVAILABLE_COPY[unavailable ?? 'failed']} excludeDetail />
            )}
            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {children}
        </div>
    )
}

export const CrossProjectTile = React.forwardRef<HTMLDivElement, CrossProjectTileProps>(CrossProjectTileInternal)
