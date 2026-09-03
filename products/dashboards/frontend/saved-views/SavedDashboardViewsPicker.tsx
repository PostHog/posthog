import { useState } from 'react'

import { IconCheck, IconChevronDown, IconPeople, IconPlus, IconUser } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Popover } from '@posthog/lemon-ui'

import { SavedViewsList } from 'lib/components/SavedViews/SavedViewsList'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import type {
    DashboardListSavedView,
    DashboardSavedViewCursors,
    DashboardSavedViewScope,
} from './dashboardSavedViewsLogic'

export interface SavedDashboardViewsPickerProps {
    activeSavedView: DashboardListSavedView | undefined
    activeSavedViewHasUnsavedChanges: boolean
    isFiltering: boolean
    savedViews: DashboardListSavedView[]
    nextCursors: DashboardSavedViewCursors
    loadingMore: boolean
    updatingSavedView: boolean
    loading: boolean
    loadError: boolean
    loadMoreFailed: boolean
    canEdit: boolean
    defaultOpen?: boolean
    onSaveAsNewView: () => void
    onSaveChanges: (view: DashboardListSavedView) => void
    onSelectView: (view: DashboardListSavedView) => void
    onManageViews: () => void
    onLoadMore: (scope: DashboardSavedViewScope) => void
    onOpen: () => void
    onRetryLoad: () => void
}

export function SavedDashboardViewsPicker({
    activeSavedView,
    activeSavedViewHasUnsavedChanges,
    isFiltering,
    savedViews,
    nextCursors,
    loadingMore,
    updatingSavedView,
    loading,
    loadError,
    loadMoreFailed,
    canEdit,
    defaultOpen = false,
    onSaveAsNewView,
    onSaveChanges,
    onSelectView,
    onManageViews,
    onLoadMore,
    onOpen,
    onRetryLoad,
}: SavedDashboardViewsPickerProps): JSX.Element {
    const [scope, setScope] = useState<DashboardSavedViewScope>(activeSavedView?.scope ?? 'private')
    const [visible, setVisible] = useState(defaultOpen)
    const privateSavedViews = savedViews
        .filter((view) => view.scope === 'private')
        .sort((left, right) => left.name.localeCompare(right.name))
    const teamSavedViews = savedViews
        .filter((view) => view.scope === 'team')
        .sort((left, right) => left.name.localeCompare(right.name))
    const selectedSavedViews = scope === 'private' ? privateSavedViews : teamSavedViews
    const hasMore = nextCursors[scope] !== null
    const hasSavedViews = savedViews.length > 0
    const tooltip = activeSavedView?.name || 'Saved views'
    const emptyScopeMessage = scope === 'private' ? 'No private views yet.' : 'No team views yet.'
    let triggerIcon: JSX.Element | undefined
    if (activeSavedView) {
        triggerIcon = activeSavedView.scope === 'private' ? <IconUser /> : <IconPeople />
    }

    const closePicker = (): void => {
        setVisible(false)
    }

    return (
        <Popover
            visible={visible}
            padded={false}
            onClickOutside={closePicker}
            overlay={
                <div className="flex w-72 flex-col py-1" data-attr="dashboard-saved-views-popover">
                    {canEdit && activeSavedViewHasUnsavedChanges && activeSavedView && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="tertiary"
                            className="h-auto justify-start rounded-none px-2 py-2 text-left"
                            icon={<IconCheck className="text-primary" />}
                            loading={updatingSavedView}
                            onClick={() => onSaveChanges(activeSavedView)}
                        >
                            <span className="flex flex-col items-start gap-1">
                                <span className="font-semibold text-primary">Save changes</span>
                                <span className="text-xs font-normal text-secondary">
                                    Current filters differ from '{activeSavedView.name}'
                                </span>
                            </span>
                        </LemonButton>
                    )}
                    {canEdit && isFiltering && (
                        <LemonButton
                            size="small"
                            fullWidth
                            type="tertiary"
                            className="h-auto justify-start rounded-none px-2 py-2 text-left"
                            icon={<IconPlus />}
                            onClick={() => {
                                closePicker()
                                onSaveAsNewView()
                            }}
                        >
                            <span className="flex flex-col items-start gap-1">
                                <span className="font-semibold">Save as new view</span>
                                <span className="text-xs font-normal text-secondary">
                                    Create a new view from these filters
                                </span>
                            </span>
                        </LemonButton>
                    )}
                    {(activeSavedView || isFiltering) && <div className="mx-3 border-t" />}
                    {loading && (
                        <div className="space-y-2 px-3 py-2" role="status" aria-label="Loading saved views">
                            <LemonSkeleton repeat={3} className="h-8" />
                        </div>
                    )}
                    {!loading && loadError && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="tertiary"
                            className="justify-start rounded-none px-3"
                            onClick={onRetryLoad}
                        >
                            Could not load saved views. Retry
                        </LemonButton>
                    )}
                    {!loading && !loadError && !hasSavedViews && !isFiltering && (
                        <div className="px-3 py-2 text-sm text-secondary">Add a filter to create a saved view.</div>
                    )}
                    {!loading && hasSavedViews && (
                        <>
                            <LemonTabs<DashboardSavedViewScope>
                                size="small"
                                activeKey={scope}
                                onChange={setScope}
                                className="px-3"
                                tabs={[
                                    {
                                        key: 'private',
                                        label: (
                                            <span className="flex items-center gap-1">
                                                Private views
                                                {activeSavedView?.scope === 'private' && (
                                                    <IconCheck className="text-success" />
                                                )}
                                            </span>
                                        ),
                                    },
                                    {
                                        key: 'team',
                                        label: (
                                            <span className="flex items-center gap-1">
                                                Shared with team
                                                {activeSavedView != null && activeSavedView.scope !== 'private' && (
                                                    <IconCheck className="text-success" />
                                                )}
                                            </span>
                                        ),
                                    },
                                ]}
                            />
                            <div className="max-h-64 overflow-y-auto">
                                <SavedViewsList
                                    views={selectedSavedViews}
                                    activeViewId={activeSavedView?.id}
                                    emptyMessage={emptyScopeMessage}
                                    onSelect={(view) => {
                                        onSelectView(view)
                                        closePicker()
                                    }}
                                />
                                {hasMore && (
                                    <div className="border-t p-2">
                                        <LemonButton
                                            fullWidth
                                            center
                                            size="small"
                                            type="secondary"
                                            loading={loadingMore}
                                            onClick={() => onLoadMore(scope)}
                                            data-attr="load-more-dashboard-saved-views"
                                        >
                                            {loadMoreFailed ? 'Could not load more views. Retry' : 'Load more views'}
                                        </LemonButton>
                                    </div>
                                )}
                            </div>
                            {canEdit && (
                                <div className="border-t">
                                    <LemonButton
                                        fullWidth
                                        size="small"
                                        type="tertiary"
                                        className="justify-start rounded-none px-3"
                                        onClick={() => {
                                            closePicker()
                                            onManageViews()
                                        }}
                                    >
                                        Manage views
                                    </LemonButton>
                                </div>
                            )}
                        </>
                    )}
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                data-attr="dashboard-saved-views-picker"
                icon={triggerIcon}
                sideIcon={<IconChevronDown />}
                tooltip={tooltip}
                aria-label={tooltip}
                onClick={() => {
                    if (!visible && activeSavedView) {
                        setScope(activeSavedView.scope ?? 'team')
                    }
                    if (!visible) {
                        onOpen()
                    }
                    setVisible(!visible)
                }}
            >
                <span className="flex items-center gap-1">
                    <span>{activeSavedView?.name || 'Saved views'}</span>
                    {canEdit && activeSavedViewHasUnsavedChanges && <span className="text-warning">Unsaved</span>}
                </span>
            </LemonButton>
        </Popover>
    )
}
