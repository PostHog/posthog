import clsx from 'clsx'
import { useValues } from 'kea'
import React, { useState } from 'react'
import { createPortal } from 'react-dom'

import { DashboardTileRefreshDataButton } from 'lib/components/Cards/InsightCard/DashboardTileRefreshDataButton'
import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { userHasAccess } from 'lib/utils/accessControlUtils'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { AccessControlLevel, AccessControlResourceType } from '~/types'
import { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import type { DashboardWidgetProductAccess } from '../../types'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import { getDashboardWidgetDefinition, type DashboardWidgetComponentProps } from '../../widgets/registry'
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
    onUpdateConfig: (config: Record<string, unknown>) => void | Promise<void>
    onUpdateMetadata?: (metadata: { name?: string; description?: string }) => void
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
            onUpdateConfig,
            onUpdateMetadata,
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
        const catalogEntry = getDashboardWidgetCatalogEntry(widget.widget_type)
        const widgetTypeLabel = catalogEntry?.groupLabel ?? catalogEntry?.label ?? widget.widget_type
        const defaultTitle = catalogEntry?.headerTitle ?? widgetTypeLabel
        const title = widget.name?.trim() || ''
        const description = widget.description?.trim() || ''
        const showDescription = tile.show_description !== false
        const headerLayout = catalogEntry?.headerLayout ?? 'dashboard_tile'
        const WidgetComponent = definition?.Component

        const handleDescriptionSave = (nextDescription: string): void => {
            onUpdateMetadata?.({ description: nextDescription })
            if (nextDescription.trim() && tile.show_description === false && toggleShowDescription) {
                toggleShowDescription()
            }
        }

        const hasProductAccess = userHasWidgetProductAccess(definition?.productAccess)

        const titleHref =
            hasProductAccess && placement !== DashboardPlacement.Public && catalogEntry?.titleHref
                ? catalogEntry.titleHref
                : undefined

        const componentProps: DashboardWidgetComponentProps = {
            tileId: tile.id,
            config: widget.config,
            result,
            loading,
            error,
            onRefresh,
            onUpdateConfig,
        }

        const EditModal = definition?.EditModal

        const widgetBody =
            hasProductAccess && WidgetComponent ? (
                <ErrorBoundary
                    className="flex min-h-0 min-w-0 flex-1 w-full max-w-full flex-col"
                    exceptionProps={{
                        feature: 'dashboard_widget',
                        widget_type: widget.widget_type,
                        tile_id: tile.id,
                    }}
                >
                    <WidgetRuntimeAvailabilityGuard
                        availability={catalogEntry?.availability}
                        unavailableContentFallback={definition?.unavailableContentFallback}
                    >
                        <WidgetComponent {...componentProps} />
                    </WidgetRuntimeAvailabilityGuard>
                </ErrorBoundary>
            ) : null

        const hasDashboardSectionActions =
            !!(onMoveToDashboard || onCopyToDashboard || onRemove) ||
            (showEditingControls && toggleShowDescription && !!description) ||
            (showEditingControls && onUpdateMetadata && !showDescription && !description)

        const refreshDisabledReason = loading ? 'Refreshing...' : undefined

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
                <WidgetCardHeader
                    layout={headerLayout}
                    title={title}
                    defaultTitle={defaultTitle}
                    titleHref={titleHref}
                    widgetTypeLabel={widgetTypeLabel}
                    config={widget.config}
                    headerMeta={catalogEntry?.headerMeta}
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
                                <LemonButton
                                    fullWidth
                                    data-attr="dashboard-widget-edit"
                                    onClick={() => setEditOpen(true)}
                                >
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
                                    {showEditingControls && onUpdateMetadata && !showDescription && !description && (
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
                    {widgetBody}
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
                                onSaveMetadata={
                                    onUpdateMetadata
                                        ? async (metadata) => {
                                              if (metadata.name !== undefined) {
                                                  onUpdateMetadata({ name: metadata.name.trim() || '' })
                                              }
                                              if (metadata.description !== undefined) {
                                                  handleDescriptionSave(metadata.description)
                                              }
                                          }
                                        : undefined
                                }
                                onSave={async (config) => {
                                    await onUpdateConfig(config)
                                }}
                            />,
                            document.body
                        )}
                </WidgetCardBody>
            </WidgetCard>
        )
    }
)

function userHasWidgetProductAccess(productAccess: DashboardWidgetProductAccess | undefined): boolean {
    if (!productAccess) {
        return true
    }

    switch (productAccess) {
        // New gated widget types: add a case here — CONTRIBUTING.md
        case 'error_tracking':
            return userHasAccess(AccessControlResourceType.ErrorTracking, AccessControlLevel.Viewer)
        default: {
            const _exhaustive: never = productAccess
            return _exhaustive
        }
    }
}
