import clsx from 'clsx'
import { useValues } from 'kea'
import React, { Suspense, useState } from 'react'
import { createPortal } from 'react-dom'

import { CardMetaRefreshButton } from 'lib/components/Cards/CardMetaRefreshButton'
import { DashboardTileRefreshDataButton } from 'lib/components/Cards/InsightCard/DashboardTileRefreshDataButton'
import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { EditModeEdge } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import {
    DEFAULT_SHARED_DASHBOARD_WIDGET_PLACEHOLDER,
    getDashboardWidgetCatalogEntry,
    getDashboardWidgetGroupLabel,
    getUnknownDashboardWidgetCatalogFallback,
    tryGetDashboardWidgetCatalogEntry,
    type ResolvedDashboardWidgetCatalogEntry,
} from '../../widget_types/catalog'
import { useWidgetAvailability } from '../../widget_types/widgetAvailability'
import {
    userCanMutateErrorTrackingIssuesOnDashboard,
    userHasDashboardWidgetProductAccess,
} from '../../widgetProductAccess'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../../widgets/constants'
import type {
    WidgetIssueMetadataContext,
    WidgetIssueMetadataDelta,
} from '../../widgets/error_tracking/applyWidgetIssueMetadataChange'
import {
    getDashboardWidgetDefinition,
    type DashboardWidgetComponentProps,
    type DashboardWidgetDefinition,
} from '../../widgets/registry'
import { WidgetCard } from '../WidgetCard/WidgetCard'
import { WidgetCardBody, WidgetCardSharedPlaceholderBody, WidgetLoadingState } from '../WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../WidgetCard/WidgetCardHeader'
import { WidgetRuntimeAvailabilityGuard } from '../WidgetRuntimeAvailabilityGuard/WidgetRuntimeAvailabilityGuard'

type DashboardWidgetItemProps = {
    tile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    dashboardId?: number | null
    canEditDashboard?: boolean
    isDashboardEditMode?: boolean
    result: unknown
    loading: boolean
    error?: string | null
    lastFetchedAt?: number
    onRefresh: () => void
    onRefreshWidgetData?: (tileId: number) => void
    onApplyWidgetIssueMetadataChange?: (
        tileId: number,
        issueId: string,
        delta: WidgetIssueMetadataDelta,
        context: WidgetIssueMetadataContext
    ) => void
    onUpdateWidgetTile?: (patch: {
        config?: Record<string, unknown>
        name?: string
        description?: string
    }) => void | Promise<void>
    toggleShowDescription?: () => void
    showResizeHandles?: boolean
    canEnterEditModeFromEdge?: boolean
    onEnterEditModeFromEdge?: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    showEditingControls?: boolean
    onDuplicate?: () => void
    onRemove?: () => void
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onCopyToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    /** Injected by react-grid-layout / react-resizable — must render inside the card root. */
    children?: React.ReactNode
} & Omit<React.HTMLAttributes<HTMLDivElement>, 'children'>

type DashboardWidgetItemContentProps = Omit<
    DashboardWidgetItemProps,
    'children' | 'className' | 'style' | 'showResizeHandles' | 'canEnterEditModeFromEdge' | 'onEnterEditModeFromEdge'
> & {
    widget: NonNullable<DashboardTile<QueryBasedInsightModel>['widget']>
    definition: DashboardWidgetDefinition | undefined
    headerCatalogEntry: ResolvedDashboardWidgetCatalogEntry
    isUnknownWidgetType: boolean
    copyToDestinations: ReturnType<typeof useValues<typeof dashboardWidgetMenusLogic>>['copyToDestinations']
    editOpen: boolean
    setEditOpen: (open: boolean) => void
}

type DashboardWidgetItemBodyProps = {
    widget: NonNullable<DashboardTile<QueryBasedInsightModel>['widget']>
    definition: DashboardWidgetDefinition | undefined
    componentProps: DashboardWidgetComponentProps
    dashboardId?: number | null
}

function DashboardWidgetItemBody({
    widget,
    definition,
    componentProps,
    dashboardId,
}: DashboardWidgetItemBodyProps): JSX.Element | null {
    const catalogEntry = getDashboardWidgetCatalogEntry(widget.widget_type)
    const WidgetComponent = definition?.Component
    const hasProductAccess = userHasDashboardWidgetProductAccess(definition?.productAccess)

    if (!hasProductAccess || !WidgetComponent) {
        return null
    }

    return (
        <WidgetRuntimeAvailabilityGuard
            availability={catalogEntry.availability}
            unavailableContentFallback={definition?.unavailableContentFallback}
            widgetType={widget.widget_type}
            widgetId={widget.id}
            dashboardId={dashboardId}
        >
            <Suspense fallback={<WidgetLoadingState />}>
                <WidgetComponent {...componentProps} />
            </Suspense>
        </WidgetRuntimeAvailabilityGuard>
    )
}

function DashboardWidgetItemContent({
    tile,
    placement,
    widget,
    definition,
    headerCatalogEntry,
    isUnknownWidgetType,
    dashboardId,
    result,
    loading,
    error,
    lastFetchedAt,
    onRefresh,
    onRefreshWidgetData,
    onApplyWidgetIssueMetadataChange,
    onUpdateWidgetTile,
    toggleShowDescription,
    onDragHandleMouseDown,
    showEditingControls,
    isDashboardEditMode,
    canEditDashboard,
    onDuplicate,
    onRemove,
    onMoveToDashboard,
    onCopyToDashboard,
    copyToDestinations,
    editOpen,
    setEditOpen,
}: DashboardWidgetItemContentProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(headerCatalogEntry.groupId)
    const defaultTitle = headerCatalogEntry.headerTitle ?? widgetTypeLabel
    const title = widget.name?.trim() || ''
    const description = widget.description?.trim() || ''
    const showDescription = tile.show_description !== false
    const headerLayout = headerCatalogEntry.headerLayout

    const hasProductAccess = userHasDashboardWidgetProductAccess(definition?.productAccess)
    const showSharedPlaceholder = placement === DashboardPlacement.Public

    const titleHref =
        hasProductAccess && !showSharedPlaceholder && headerCatalogEntry.titleHref
            ? headerCatalogEntry.titleHref
            : undefined

    const canUpdateWidgetTileConfig = !!onUpdateWidgetTile && !!canEditDashboard

    const componentProps: DashboardWidgetComponentProps = {
        tileId: tile.id,
        config: widget.config,
        result,
        loading,
        error,
        onRefresh,
        onRefreshData: onRefreshWidgetData ? () => onRefreshWidgetData(tile.id) : undefined,
        onApplyIssueMetadataChange: onApplyWidgetIssueMetadataChange
            ? (issueId, delta, context) => {
                  onApplyWidgetIssueMetadataChange(tile.id, issueId, delta, context)
              }
            : undefined,
        canMutateErrorTrackingIssues: userCanMutateErrorTrackingIssuesOnDashboard(!!canEditDashboard),
        onUpdateConfig: canUpdateWidgetTileConfig
            ? async (config) => {
                  await onUpdateWidgetTile({ config })
              }
            : undefined,
    }

    const TileFilters = definition?.TileFilters
    const { isAvailable: showTileFilters } = useWidgetAvailability(headerCatalogEntry.availability)
    const EditModal = definition?.EditModal

    const hasDashboardSectionActions =
        !!(onMoveToDashboard || onCopyToDashboard || onRemove) ||
        (showEditingControls && toggleShowDescription && !!description) ||
        (showEditingControls && onUpdateWidgetTile && !showDescription && !description)

    const refreshDisabledReason = loading ? 'Refreshing...' : undefined

    // Refresh icon revealed on tile hover, mirroring insight tiles. Gated on editing controls so it
    // stays off public/export dashboards, and hidden while the tile is loading (refresh stays reachable
    // via the always-present "⋯" menu for touch/keyboard). CardMeta's CSS handles the hover reveal.
    const showHoverRefresh =
        !!showEditingControls && !isUnknownWidgetType && headerLayout === 'dashboard_tile' && !loading
    const refreshControl = showHoverRefresh ? (
        <CardMetaRefreshButton onRefresh={onRefresh} lastRefresh={lastFetchedAt} dataAttr="dashboard-widget-refresh" />
    ) : null

    return (
        <>
            <WidgetCardHeader
                layout={headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widget.config}
                headerMeta={headerCatalogEntry.headerMeta}
                TopHeading={definition?.TopHeading}
                description={description}
                showDescription={showDescription}
                loading={loading}
                showEditingControls={showEditingControls}
                isDashboardEditMode={isDashboardEditMode}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(placement, showEditingControls)}
                refreshControl={refreshControl}
                moreButtonOverlay={
                    <>
                        {titleHref && (
                            <LemonButton to={titleHref} fullWidth>
                                View
                            </LemonButton>
                        )}
                        {showEditingControls && EditModal && (
                            <LemonButton fullWidth data-attr="dashboard-widget-edit" onClick={() => setEditOpen(true)}>
                                Edit
                            </LemonButton>
                        )}
                        {onDuplicate && (
                            <LemonButton fullWidth onClick={onDuplicate}>
                                Duplicate
                            </LemonButton>
                        )}
                        {hasDashboardSectionActions && (
                            <>
                                <LemonDivider />
                                <h5 className="mx-2 my-1">Dashboard</h5>
                                {showEditingControls && onUpdateWidgetTile && !showDescription && !description && (
                                    <LemonButton
                                        fullWidth
                                        onClick={() => {
                                            toggleShowDescription?.()
                                            setEditOpen(true)
                                        }}
                                    >
                                        Add description
                                    </LemonButton>
                                )}
                                {showEditingControls && toggleShowDescription && !!description && (
                                    <LemonButton fullWidth onClick={toggleShowDescription}>
                                        {tile.show_description === false ? 'Show description' : 'Hide description'}
                                    </LemonButton>
                                )}
                                {(onMoveToDashboard || onCopyToDashboard) && (
                                    <DashboardWidgetPlacementMenus
                                        placementDestinations={copyToDestinations ?? []}
                                        onMoveToDashboard={onMoveToDashboard}
                                        onCopyToDashboard={onCopyToDashboard}
                                    />
                                )}
                                {onRemove && (
                                    <LemonButton status="danger" fullWidth onClick={onRemove}>
                                        Remove from dashboard
                                    </LemonButton>
                                )}
                            </>
                        )}
                        {onRefresh && headerLayout === 'dashboard_tile' && !isUnknownWidgetType && (
                            <>
                                <LemonDivider />
                                <DashboardTileRefreshDataButton
                                    onRefresh={onRefresh}
                                    disabledReason={refreshDisabledReason}
                                    lastRefresh={lastFetchedAt}
                                />
                            </>
                        )}
                    </>
                }
                onDragHandleMouseDown={onDragHandleMouseDown}
            />
            {!showSharedPlaceholder && hasProductAccess && showTileFilters && TileFilters ? (
                <Suspense fallback={null}>
                    <TileFilters
                        tileId={tile.id}
                        config={widget.config}
                        onUpdateConfig={componentProps.onUpdateConfig}
                        canMutateErrorTrackingIssues={componentProps.canMutateErrorTrackingIssues}
                        disabledReason={
                            canUpdateWidgetTileConfig ? undefined : DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON
                        }
                    />
                </Suspense>
            ) : null}
            {showSharedPlaceholder ? (
                <WidgetCardSharedPlaceholderBody
                    copy={headerCatalogEntry.sharedPlaceholder ?? DEFAULT_SHARED_DASHBOARD_WIDGET_PLACEHOLDER}
                />
            ) : (
                <WidgetCardBody
                    locked={!hasProductAccess}
                    error={!isUnknownWidgetType && hasProductAccess ? error : undefined}
                    onRefresh={isUnknownWidgetType ? undefined : onRefresh}
                    refreshing={isUnknownWidgetType ? false : loading}
                >
                    <ErrorBoundary
                        className="flex min-h-0 min-w-0 flex-1 w-full max-w-full flex-col"
                        exceptionProps={{
                            feature: 'dashboard_widget',
                            widget_type: widget.widget_type,
                            tile_id: tile.id,
                        }}
                    >
                        <DashboardWidgetItemBody
                            widget={widget}
                            definition={definition}
                            componentProps={componentProps}
                            dashboardId={dashboardId}
                        />
                    </ErrorBoundary>
                </WidgetCardBody>
            )}
            {EditModal &&
                editOpen &&
                createPortal(
                    <Suspense fallback={null}>
                        <EditModal
                            isOpen={editOpen}
                            onClose={() => setEditOpen(false)}
                            config={widget.config}
                            name={title}
                            defaultTitle={defaultTitle}
                            description={description}
                            onSave={async (config, metadata) => {
                                await onUpdateWidgetTile?.({ config, ...metadata })
                            }}
                        />
                    </Suspense>,
                    document.body
                )}
        </>
    )
}

export const DashboardWidgetItem = React.forwardRef<HTMLDivElement, DashboardWidgetItemProps>(
    function DashboardWidgetItem(
        {
            tile,
            placement,
            dashboardId,
            canEditDashboard,
            isDashboardEditMode,
            result,
            loading,
            error,
            lastFetchedAt,
            onRefresh,
            onRefreshWidgetData,
            onApplyWidgetIssueMetadataChange,
            onUpdateWidgetTile,
            toggleShowDescription,
            showResizeHandles,
            canEnterEditModeFromEdge,
            onEnterEditModeFromEdge,
            onDragHandleMouseDown,
            showEditingControls,
            onDuplicate,
            onRemove,
            onMoveToDashboard,
            onCopyToDashboard,
            children,
            className,
            style,
            ...divProps
        },
        ref
    ): JSX.Element | null {
        const widget = tile.widget
        const [editOpen, setEditOpen] = useState(false)

        const { copyToDestinations } = useValues(
            dashboardWidgetMenusLogic({
                instanceKey: widget ? `widget-${widget.id}` : `widget-tile-${tile.id}`,
                dashboardId,
                dashboards: undefined,
                dashboard_tiles: widget?.dashboard_tiles,
            })
        )

        if (!widget) {
            return null
        }

        const definition = getDashboardWidgetDefinition(widget.widget_type, {
            tileId: tile.id,
            dashboardId: dashboardId ?? undefined,
        })
        const catalogEntryOrUndefined = tryGetDashboardWidgetCatalogEntry(widget.widget_type)
        const headerCatalogEntry =
            catalogEntryOrUndefined ?? getUnknownDashboardWidgetCatalogFallback(widget.widget_type)
        const isUnknownWidgetType = catalogEntryOrUndefined === undefined

        // react-grid-layout injects className/style via cloneElement — WidgetCard must be the root node
        // so decorative resize handles and RGL's .react-resizable-handle siblings share a parent (see InsightCard).
        return (
            <WidgetCard
                ref={ref}
                className={clsx('min-h-0', className)}
                style={style}
                {...divProps}
                showResizeHandles={showResizeHandles}
                canEnterEditModeFromEdge={canEnterEditModeFromEdge}
                onEnterEditModeFromEdge={onEnterEditModeFromEdge}
                gridChildren={children}
            >
                <DashboardWidgetItemContent
                    tile={tile}
                    placement={placement}
                    widget={widget}
                    definition={definition}
                    headerCatalogEntry={headerCatalogEntry}
                    isUnknownWidgetType={isUnknownWidgetType}
                    dashboardId={dashboardId}
                    result={result}
                    loading={loading}
                    error={error}
                    lastFetchedAt={lastFetchedAt}
                    onRefresh={onRefresh}
                    onRefreshWidgetData={onRefreshWidgetData}
                    onApplyWidgetIssueMetadataChange={onApplyWidgetIssueMetadataChange}
                    onUpdateWidgetTile={onUpdateWidgetTile}
                    canEditDashboard={canEditDashboard}
                    toggleShowDescription={toggleShowDescription}
                    isDashboardEditMode={isDashboardEditMode}
                    onDragHandleMouseDown={onDragHandleMouseDown}
                    showEditingControls={showEditingControls}
                    onDuplicate={onDuplicate}
                    onRemove={onRemove}
                    onMoveToDashboard={onMoveToDashboard}
                    onCopyToDashboard={onCopyToDashboard}
                    copyToDestinations={copyToDestinations}
                    editOpen={editOpen}
                    setEditOpen={setEditOpen}
                />
            </WidgetCard>
        )
    }
)
