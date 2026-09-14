import { deepEqual as isEqual } from 'fast-equals'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonDialog, LemonInput, LemonTag, lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { fullName } from 'lib/utils/strings'
import {
    DEFAULT_FILTERS,
    DashboardsFilters,
    DashboardsTab,
    dashboardsLogic,
} from 'scenes/dashboard/dashboards/dashboardsLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    dashboardSavedViewsCreate,
    dashboardSavedViewsDestroy,
    dashboardSavedViewsPartialUpdate,
} from '../generated/api'
import type { PatchedDashboardSavedViewApi } from '../generated/api.schemas'
import {
    DashboardListSavedView,
    DashboardSavedViewScope,
    DashboardSavedViewsPage,
    dashboardListSavedView,
    dashboardSavedViewsLogic,
    loadDashboardSavedViews,
} from './dashboardSavedViewsLogic'
import { ManageDashboardSavedViews } from './ManageDashboardSavedViews'
import { SavedDashboardViewsPicker } from './SavedDashboardViewsPicker'

function savedViewFilterProperties(filters: DashboardsFilters): Record<string, boolean | number> {
    const tagCount = filters.tags?.length ?? 0
    const hasSearch = Boolean(filters.search)
    const hasFolder = filters.folder != null
    const hasTags = tagCount > 0
    const hasCreator = Array.isArray(filters.createdBy) && filters.createdBy.length > 0

    return {
        has_search_filter: hasSearch,
        has_folder_filter: hasFolder,
        has_tag_filter: hasTags,
        tag_count: tagCount,
        has_creator_filter: hasCreator,
        is_pinned: filters.pinned,
        is_shared: filters.shared,
        active_filter_count: [hasSearch, hasFolder, hasTags, hasCreator, filters.pinned, filters.shared].filter(Boolean)
            .length,
    }
}

function savedViewFilters(view: DashboardListSavedView): DashboardsFilters {
    return {
        ...DEFAULT_FILTERS,
        ...view.filters,
    }
}

function SavedViewVisibilityPicker({
    initialScope,
    onChange,
}: {
    initialScope: DashboardSavedViewScope
    onChange: (scope: DashboardSavedViewScope) => void
}): JSX.Element {
    const [scope, setScope] = useState<DashboardSavedViewScope>(initialScope)

    const selectScope = (nextScope: DashboardSavedViewScope): void => {
        setScope(nextScope)
        onChange(nextScope)
    }

    return (
        <div className="flex items-center gap-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-secondary">Visibility</div>
            <LemonRadio<DashboardSavedViewScope>
                value={scope}
                onChange={selectScope}
                orientation="horizontal"
                aria-label="View visibility"
                options={[
                    {
                        value: 'private',
                        label: 'Private',
                    },
                    {
                        value: 'team',
                        label: 'Shared with team',
                        disabledReason:
                            getAccessControlDisabledReason(
                                AccessControlResourceType.Dashboard,
                                AccessControlLevel.Editor
                            ) ?? undefined,
                    },
                ]}
            />
        </div>
    )
}

export function DashboardSavedViews(): JSX.Element | null {
    const { setFilters, setSearch } = useActions(dashboardsLogic)
    const { currentTab, filters, isFiltering } = useValues(dashboardsLogic)
    const { selectableMembers } = useValues(membersLogic)
    const { currentTeamId } = useValues(teamLogic)
    const savedViewsLogic = dashboardSavedViewsLogic({ teamId: currentTeamId })
    const {
        dashboardSavedViewsEnabled,
        savedViews,
        savedViewsNextCursors,
        loadMoreSavedViewsLoading,
        savedViewsLoading,
        savedViewsLoadError,
        savedViewsLoadMoreFailed,
        activeSavedViewId,
    } = useValues(savedViewsLogic)
    const {
        loadSavedViews,
        loadMoreSavedViews,
        loadMoreSavedViewsSuccess,
        savedViewCreated,
        savedViewDeleted,
        savedViewUpdated,
        setActiveSavedViewId,
    } = useActions(savedViewsLogic)
    const [updatingSavedView, setUpdatingSavedView] = useState(false)
    const activeSavedView = savedViews.find((view) => view.id === activeSavedViewId)
    const activeSavedViewHasUnsavedChanges =
        activeSavedView != null && !isEqual(filters, savedViewFilters(activeSavedView))
    const membersById = Object.fromEntries(selectableMembers().map((member) => [member.user.id, member]))
    const savedViewCreatorName = (view: DashboardListSavedView): string => {
        if (view.created_by == null) {
            return 'Unknown user'
        }
        const viewCreator = membersById[view.created_by]?.user
        return viewCreator ? fullName(viewCreator) || viewCreator.email : `User ${view.created_by}`
    }
    const savedFiltersSummary = (viewFilters: DashboardsFilters): JSX.Element => (
        <div>
            <div className="text-sm text-secondary">This view saves:</div>
            <ul className="list-disc space-y-2 pl-5 text-sm">
                {viewFilters.shared && <li>Shared dashboards</li>}
                {viewFilters.pinned && <li>Pinned dashboards</li>}
                {viewFilters.tags && viewFilters.tags.length > 0 && (
                    <li>
                        <div className="flex flex-wrap items-center gap-1">
                            <span>Tags:</span>
                            <ObjectTags tags={viewFilters.tags} staticOnly />
                        </div>
                    </li>
                )}
                {viewFilters.createdBy !== 'All users' && (
                    <li>
                        <div className="flex flex-wrap items-center gap-1">
                            <span>Created by:</span>
                            {viewFilters.createdBy.map((id) => {
                                const member = membersById[id]
                                const name = member ? fullName(member.user) || member.user.email : `User ${id}`

                                return (
                                    <LemonTag
                                        key={id}
                                        size="medium"
                                        icon={<ProfilePicture user={member?.user} name={name} size="sm" />}
                                    >
                                        {name}
                                    </LemonTag>
                                )
                            })}
                        </div>
                    </li>
                )}
                {viewFilters.folder != null && <li>Folder: {viewFilters.folder || 'Project root'}</li>}
                {viewFilters.search && <li>Search: “{viewFilters.search}”</li>}
            </ul>
        </div>
    )
    const savedViewsEditDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        AccessControlLevel.Editor
    )

    const saveView = (initialScope: DashboardSavedViewScope = 'private'): void => {
        if (!isFiltering) {
            lemonToast.error('Add a filter before saving a view')
            return
        }
        let scope = initialScope
        LemonDialog.openForm({
            title: 'Save as new view',
            initialValues: { name: 'My view' },
            content: (
                <div className="space-y-6">
                    {savedFiltersSummary(filters)}
                    <LemonField name="name">
                        <LemonInput autoFocus placeholder="View name" />
                    </LemonField>
                    <SavedViewVisibilityPicker initialScope={scope} onChange={(value) => (scope = value)} />
                </div>
            ),
            errors: {
                name: (value) => (!value?.trim() ? 'Enter a view name' : undefined),
            },
            showErrorsOnTouch: true,
            onSubmit: async ({ name }) => {
                const trimmedName = name.trim()
                if (currentTeamId == null) {
                    return
                }
                const teamId = currentTeamId
                try {
                    const savedView = await dashboardSavedViewsCreate(teamId.toString(), {
                        name: trimmedName,
                        filters,
                        scope,
                    })
                    if (teamId === teamLogic.values.currentTeamId) {
                        savedViewCreated(dashboardListSavedView(savedView))
                        setActiveSavedViewId(savedView.id)
                        lemonToast.success(scope === 'private' ? 'Saved private view' : 'Saved view shared with team')
                    }
                } catch (error) {
                    const detail = error instanceof ApiError ? error.detail : null
                    lemonToast.error(detail || 'Could not save this view. Try again.')
                    throw error
                }
            },
            primaryButtonProps: {
                children: 'Save view',
            },
            shouldAwaitSubmit: true,
            width: 600,
            zIndex: '1169',
        })
    }

    const deleteSavedView = async (view: DashboardListSavedView): Promise<void> => {
        if (currentTeamId == null) {
            return
        }
        const teamId = currentTeamId
        try {
            await dashboardSavedViewsDestroy(teamId.toString(), view.id)
            if (teamId === teamLogic.values.currentTeamId) {
                savedViewDeleted(view.id)
                lemonToast.success('Saved view deleted')
            }
        } catch (error) {
            const detail = error instanceof ApiError ? error.detail : null
            lemonToast.error(detail || 'Could not delete this view. Try again.')
            throw error
        }
    }

    const updateSavedViewMetadata = async (
        view: DashboardListSavedView,
        update: Pick<PatchedDashboardSavedViewApi, 'name' | 'scope'>
    ): Promise<DashboardListSavedView> => {
        if (currentTeamId == null) {
            throw new Error('No project selected')
        }
        const teamId = currentTeamId
        try {
            const savedView = await dashboardSavedViewsPartialUpdate(teamId.toString(), view.id, update)
            const updatedView = dashboardListSavedView(savedView)
            if (teamId === teamLogic.values.currentTeamId) {
                savedViewUpdated(updatedView)
                lemonToast.success('Saved view updated')
            }
            return updatedView
        } catch (error) {
            const detail = error instanceof ApiError ? error.detail : null
            lemonToast.error(detail || 'Could not update this view. Try again.')
            throw error
        }
    }

    const savedFiltersDescription = (viewFilters: DashboardsFilters): string => {
        const descriptions: string[] = []
        if (viewFilters.shared) {
            descriptions.push('Shared dashboards')
        }
        if (viewFilters.pinned) {
            descriptions.push('Pinned dashboards')
        }
        if (viewFilters.tags?.length) {
            descriptions.push(`Tags: ${viewFilters.tags.join(', ')}`)
        }
        const createdBy = viewFilters.createdBy === 'All users' ? [] : viewFilters.createdBy || []
        if (createdBy.length > 0) {
            const creators = createdBy.map((id) => {
                const member = membersById[id]
                return member ? fullName(member.user) || member.user.email : `User ${id}`
            })
            descriptions.push(`Created by: ${creators.join(', ')}`)
        }
        if (viewFilters.folder != null) {
            descriptions.push(`Folder: ${viewFilters.folder || 'Project root'}`)
        }
        if (viewFilters.search) {
            descriptions.push(`Search: “${viewFilters.search}”`)
        }
        return descriptions.length > 0 ? descriptions.join(', ') : 'No filters'
    }

    const loadMoreSavedViewsForManagement = async (
        scope: DashboardSavedViewScope,
        cursor: string
    ): Promise<DashboardSavedViewsPage | null> => {
        if (currentTeamId == null) {
            return null
        }
        const teamId = currentTeamId
        const page = await loadDashboardSavedViews(teamId, scope, cursor)
        if (teamId !== teamLogic.values.currentTeamId) {
            return null
        }
        loadMoreSavedViewsSuccess(page)
        return page
    }

    const manageSavedViews = (): void => {
        LemonDialog.open({
            title: 'Manage saved views',
            content: (
                <ManageDashboardSavedViews
                    views={savedViews}
                    nextCursors={savedViewsNextCursors}
                    editDisabledReason={savedViewsEditDisabledReason}
                    onUpdate={updateSavedViewMetadata}
                    onDelete={deleteSavedView}
                    onLoadMore={loadMoreSavedViewsForManagement}
                    renderCreator={(view) => {
                        const creator = view.created_by ? membersById[view.created_by]?.user : null
                        return (
                            <span className="flex items-center gap-2">
                                <ProfilePicture user={creator} name={savedViewCreatorName(view)} size="md" />
                                <span>{savedViewCreatorName(view)}</span>
                            </span>
                        )
                    }}
                    renderFilters={savedFiltersDescription}
                />
            ),
            primaryButton: null,
            secondaryButton: { children: 'Close' },
            width: 1100,
            maxWidth: 'calc(100vw - 2rem)',
            zIndex: '1169',
        })
    }

    const updateSavedView = async (view: DashboardListSavedView): Promise<void> => {
        if (currentTeamId == null || updatingSavedView) {
            return
        }
        const teamId = currentTeamId
        setUpdatingSavedView(true)
        try {
            const savedView = await dashboardSavedViewsPartialUpdate(teamId.toString(), view.id, {
                filters,
            })
            if (teamId === teamLogic.values.currentTeamId) {
                savedViewUpdated(dashboardListSavedView(savedView))
                lemonToast.success('Saved view updated')
            }
        } catch (error) {
            const detail = error instanceof ApiError ? error.detail : null
            lemonToast.error(detail || 'Could not update this view. Try again.')
        } finally {
            setUpdatingSavedView(false)
        }
    }

    if (!dashboardSavedViewsEnabled || currentTab !== DashboardsTab.All) {
        return null
    }

    return (
        <SavedDashboardViewsPicker
            activeSavedView={activeSavedView}
            activeSavedViewHasUnsavedChanges={activeSavedViewHasUnsavedChanges}
            isFiltering={isFiltering}
            savedViews={savedViews}
            nextCursors={savedViewsNextCursors}
            loadingMore={loadMoreSavedViewsLoading}
            updatingSavedView={updatingSavedView}
            loading={savedViewsLoading}
            loadError={savedViewsLoadError}
            loadMoreFailed={savedViewsLoadMoreFailed}
            canEdit={!savedViewsEditDisabledReason && !savedViewsLoading}
            onSaveAsNewView={saveView}
            onSaveChanges={(view) => void updateSavedView(view)}
            onSelectView={(view) => {
                if (activeSavedViewId === view.id) {
                    setActiveSavedViewId(null)
                    return
                }
                posthog.capture('dashboard saved view applied', {
                    scope: view.scope,
                    ...savedViewFilterProperties(view.filters),
                })
                const nextFilters = savedViewFilters(view)
                setFilters({ ...nextFilters, search: '' })
                setSearch(nextFilters.search)
                setActiveSavedViewId(view.id)
            }}
            onManageViews={manageSavedViews}
            onLoadMore={loadMoreSavedViews}
            onRetryLoad={loadSavedViews}
        />
    )
}
