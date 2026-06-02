import clsx from 'clsx'
import { useValues } from 'kea'
import React, { useState } from 'react'
import { createPortal } from 'react-dom'

import { DashboardTileRefreshDataButton } from 'lib/components/Cards/InsightCard/DashboardTileRefreshDataButton'
import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import {
    getDashboardWidgetCatalogEntry,
    getDashboardWidgetGroupLabel,
    getUnknownDashboardWidgetCatalogFallback,
    tryGetDashboardWidgetCatalogEntry,
    type ResolvedDashboardWidgetCatalogEntry,
} from '../../widget_types/catalog'
import { userHasDashboardWidgetProductAccess } from '../../widgetProductAccess'
import {
    getDashboardWidgetDefinition,
    type DashboardWidgetComponentProps,
    type DashboardWidgetDefinition,
} from '../../widgets/registry'
import { WidgetCard } from '../WidgetCard/WidgetCard'
import { WidgetCardBody } from '../WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../WidgetCard/WidgetCardHeader'
import { WidgetRuntimeAvailabilityGuard } from '../WidgetRuntimeAvailabilityGuard/WidgetRuntimeAvailabilityGuard'

type DashboardWidgetItemProps = {
    tile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    dashboardId?: number | null
    result: unknown
    loading: boolean
    error?: string | null
    lastFetchedAt?: number
    onRefresh: () => void
    onUpdateWidgetTile?: (patch: {
        config?: Record<string, unknown>
        name?: string
        description?: string
    }) => void | Promise<void>
    toggleShowDescription?: () => void
    showResizeHandles?: boolean
    canEnterEditModeFromEdge?: boolean
    onEnterEditModeFromEdge?: () => void
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
    copyToDestinations: ReturnType<typeof useValues<typeof dashboardWidgetMenusLogic>>['copyToDestinations']
    editOpen: boolean
    setEditOpen: (open: boolean) => void
}

type DashboardWidgetItemBodyProps = {
    widget: NonNullable<DashboardTile<QueryBasedInsightModel>['widget']>
    definition: DashboardWidgetDefinition | undefined
    componentProps: DashboardWidgetComponentProps
}

function DashboardWidgetItemBody({
    widget,
    definition,
    componentProps,
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
        >
            <WidgetComponent {...componentProps} />
        </WidgetRuntimeAvailabilityGuard>
    )
}

function DashboardWidgetItemContent({
    tile,
    placement,
    widget,
    definition,
    headerCatalogEntry,
    result,
    loading,
    error,
    lastFetchedAt,
    onRefresh,
    onUpdateWidgetTile,
    toggleShowDescription,
    onDragHandleMouseDown,
    showEditingControls,
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

    const titleHref =
        hasProductAccess && placement !== DashboardPlacement.Public && headerCatalogEntry.titleHref
            ? headerCatalogEntry.titleHref
            : undefined

    const componentProps: DashboardWidgetComponentProps = {
        tileId: tile.id,
        config: widget.config,
        result,
        loading,
        error,
        onRefresh,
        onUpdateConfig: onUpdateWidgetTile
            ? async (config) => {
                  await onUpdateWidgetTile({ config })
              }
            : undefined,
    }

    const EditModal = definition?.EditModal

    const hasDashboardSectionActions =
        !!(onMoveToDashboard || onCopyToDashboard || onRemove) ||
        (showEditingControls && toggleShowDescription && !!description) ||
        (showEditingControls && onUpdateWidgetTile && !showDescription && !description)

    const refreshDisabledReason = loading ? 'Refreshing...' : undefined

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
                description={description}
                showDescription={showDescription}
                loading={loading}
                showEditingControls={showEditingControls}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(placement, showEditingControls)}
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
                        {onRefresh && headerLayout === 'dashboard_tile' && (
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
            <WidgetCardBody
                locked={!hasProductAccess}
                error={hasProductAccess ? error : undefined}
                onRefresh={onRefresh}
                refreshing={loading}
            >
                <ErrorBoundary
                    className="flex min-h-0 min-w-0 flex-1 w-full max-w-full flex-col"
                    exceptionProps={{
                        feature: 'dashboard_widget',
                        widget_type: widget.widget_type,
                        tile_id: tile.id,
                    }}
                >
                    <DashboardWidgetItemBody widget={widget} definition={definition} componentProps={componentProps} />
                </ErrorBoundary>
                {EditModal &&
                    editOpen &&
                    createPortal(
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
                        />,
                        document.body
                    )}
            </WidgetCardBody>
        </>
    )
}

export const DashboardWidgetItem = React.forwardRef<HTMLDivElement, DashboardWidgetItemProps>(
    function DashboardWidgetItem(
        {
            tile,
            placement,
            dashboardId,
            result,
            loading,
            error,
            lastFetchedAt,
            onRefresh,
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
        const headerCatalogEntry =
            tryGetDashboardWidgetCatalogEntry(widget.widget_type) ??
            getUnknownDashboardWidgetCatalogFallback(widget.widget_type)

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
                    result={result}
                    loading={loading}
                    error={error}
                    lastFetchedAt={lastFetchedAt}
                    onRefresh={onRefresh}
                    onUpdateWidgetTile={onUpdateWidgetTile}
                    toggleShowDescription={toggleShowDescription}
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
