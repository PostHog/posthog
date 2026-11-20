import type { ReactNode } from 'react'

import { IconChevronDown, IconGlobe, IconPencil, IconPlus, IconUser } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, LemonMenuItems, Tooltip } from '@posthog/lemon-ui'

import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

export interface SavedViewSelectorProps {
    views: ColumnConfigurationApi[]
    currentView: ColumnConfigurationApi | null
    currentViewId: string | null
    currentViewName?: string | null
    isDirty: boolean
    viewsLoading: boolean
    viewsLoaded: boolean
    viewsLoadError: boolean
    awaitingSavedView?: boolean
    onSelect: (id: string) => void
    onUpdate: (id: string) => void
    onEdit: (id: string) => void
    onDelete: (id: string) => void
    onCreate: () => void
    onRetry: () => void
    onVisibilityChange?: (open: boolean) => void
    resetOption?: { label: string; onClick: () => void }
    renderViewTooltip?: (view: ColumnConfigurationApi) => ReactNode
    dataAttrPrefix: string
}

function ViewVisibilityIcon({ view }: { view: ColumnConfigurationApi }): JSX.Element {
    return (
        <Tooltip
            title={
                view.visibility === 'private'
                    ? 'Only you can see this view.'
                    : 'Everyone on your team can see this view.'
            }
        >
            {view.visibility === 'private' ? <IconUser /> : <IconGlobe />}
        </Tooltip>
    )
}

export function SavedViewSelector({
    views,
    currentView,
    currentViewId,
    currentViewName,
    isDirty,
    viewsLoading,
    viewsLoaded,
    viewsLoadError,
    awaitingSavedView = false,
    onSelect,
    onUpdate,
    onEdit,
    onDelete,
    onCreate,
    onRetry,
    onVisibilityChange,
    resetOption,
    renderViewTooltip,
    dataAttrPrefix,
}: SavedViewSelectorProps): JSX.Element {
    const menuItems: LemonMenuItems = [
        resetOption
            ? {
                  items: [
                      {
                          ...resetOption,
                          active: currentViewId === null,
                          'data-attr': `${dataAttrPrefix}-clear-view`,
                      },
                  ],
              }
            : null,
        {
            items: views.map(
                (view): LemonMenuItem => ({
                    label: view.name ?? 'Untitled view',
                    icon: <ViewVisibilityIcon view={view} />,
                    active: currentViewId === view.id,
                    onClick: () => onSelect(view.id),
                    tooltip: renderViewTooltip?.(view),
                    tooltipPlacement: 'right',
                    sideAction: {
                        icon: <IconPencil />,
                        tooltip: 'Manage view',
                        dropdown: {
                            overlay: (
                                <>
                                    <LemonButton
                                        size="small"
                                        fullWidth
                                        onClick={() => onEdit(view.id)}
                                        data-attr={`${dataAttrPrefix}-edit-view`}
                                    >
                                        Edit
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        fullWidth
                                        status="danger"
                                        onClick={() => onDelete(view.id)}
                                        data-attr={`${dataAttrPrefix}-delete-view`}
                                    >
                                        Delete
                                    </LemonButton>
                                </>
                            ),
                        },
                    },
                })
            ),
        },
        {
            items: [
                {
                    label: 'Save as new view...',
                    icon: <IconPlus />,
                    onClick: onCreate,
                    disabledReason: awaitingSavedView ? 'Wait for saved views to load' : undefined,
                },
            ],
        },
    ]

    return (
        <div className="flex flex-wrap items-center gap-2 min-w-0" data-attr={`${dataAttrPrefix}-views`}>
            {viewsLoadError && (
                <LemonButton
                    size="small"
                    type="secondary"
                    status="danger"
                    onClick={onRetry}
                    loading={viewsLoading}
                    data-attr={`${dataAttrPrefix}-retry-views`}
                >
                    Couldn't load views. Retry
                </LemonButton>
            )}
            {views.length > 0 || currentViewId || !viewsLoaded || viewsLoadError ? (
                <LemonMenu items={menuItems} closeOnClickInside onVisibilityChange={onVisibilityChange}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        sideIcon={<IconChevronDown />}
                        icon={
                            currentView ? (
                                <ViewVisibilityIcon view={currentView} />
                            ) : currentViewId ? (
                                <span className="h-4 w-4" aria-hidden />
                            ) : undefined
                        }
                        tooltip={currentView ? renderViewTooltip?.(currentView) : undefined}
                        className="max-w-full"
                        data-attr={`${dataAttrPrefix}-select-view`}
                    >
                        <span className="truncate">{currentView?.name ?? currentViewName ?? 'Select view'}</span>
                    </LemonButton>
                </LemonMenu>
            ) : (
                <LemonButton
                    icon={<IconPlus />}
                    size="small"
                    type="secondary"
                    onClick={onCreate}
                    loading={viewsLoading && awaitingSavedView}
                    disabledReason={awaitingSavedView ? 'Wait for saved views to load' : undefined}
                    data-attr={`${dataAttrPrefix}-save-view`}
                >
                    Save current view
                </LemonButton>
            )}
            {currentView && isDirty && (
                <LemonButton
                    size="small"
                    type="secondary"
                    tooltip="Update this view with the current configuration"
                    loading={viewsLoading}
                    onClick={() => onUpdate(currentView.id)}
                    className="max-w-full"
                    data-attr={`${dataAttrPrefix}-update-view`}
                >
                    <span className="truncate">Update "{currentView.name}"</span>
                </LemonButton>
            )}
        </div>
    )
}
