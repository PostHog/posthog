import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_COLUMN_CONFIG_KEY, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { accountsLogic } from './accountsLogic'
import { accountsOverviewTilesLogic } from './accountsOverviewTilesLogic'
import type { accountsViewsLogicType } from './accountsViewsLogicType'
import {
    AccountsViewProperties,
    AccountsViewState,
    deserializeAccountsView,
    serializeAccountsView,
} from './accountsViewState'
import { AccountsEvents, DEFAULT_TILES } from './constants'

export type ViewVisibility = 'private' | 'shared'

export const accountsViewsLogic = kea<accountsViewsLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsViewsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user'],
            accountsColumnConfigLogic,
            ['selectColumns'],
            accountsLogic,
            [
                'searchQuery',
                'tagsFilter',
                'allRolesUnassigned',
                'csmFilter',
                'accountExecutiveFilter',
                'accountOwnerFilter',
                'sortOrder',
            ],
            accountsOverviewTilesLogic,
            ['tiles', 'tileFilter'],
        ],
        actions: [
            accountsColumnConfigLogic,
            ['setSelectColumns'],
            accountsLogic,
            [
                'setSearchQuery',
                'setTagsFilter',
                'setAllRolesUnassigned',
                'setCsmFilter',
                'setAccountExecutiveFilter',
                'setAccountOwnerFilter',
                'setSortOrder',
            ],
            accountsOverviewTilesLogic,
            ['setTiles', 'setTileFilter'],
        ],
    })),
    actions({
        selectView: (id: string) => ({ id }),
        applyView: (view: ColumnConfigurationApi) => ({ view }),
        setCurrentViewId: (id: string | null) => ({ id }),
        setIsCreating: (isCreating: boolean) => ({ isCreating }),
        setViewToDelete: (id: string | null) => ({ id }),
    }),
    loaders(({ values }) => ({
        views: [
            [] as ColumnConfigurationApi[],
            {
                loadViews: async (): Promise<ColumnConfigurationApi[]> => {
                    const response = await api.columnConfigurations.list({ context_key: ACCOUNTS_COLUMN_CONFIG_KEY })
                    return response.results
                },
                updateView: async ({
                    id,
                    updates,
                }: {
                    id: string
                    updates: Partial<ColumnConfigurationApi>
                }): Promise<ColumnConfigurationApi[]> => {
                    const data =
                        Object.keys(updates).length === 0 ? serializeAccountsView(values.liveViewState) : updates
                    const response = await api.columnConfigurations.update({ id, data })
                    return values.views.map((view) => (view.id === id ? response : view))
                },
                deleteView: async ({ id }: { id: string }): Promise<ColumnConfigurationApi[]> => {
                    await api.columnConfigurations.delete({ id })
                    return values.views.filter((view) => view.id !== id)
                },
                patchViewProperties: async ({
                    id,
                    properties,
                }: {
                    id: string
                    properties: AccountsViewProperties
                }): Promise<ColumnConfigurationApi[]> => {
                    const response = await api.columnConfigurations.update({ id, data: { properties } })
                    return values.views.map((view) => (view.id === id ? response : view))
                },
            },
        ],
    })),
    reducers(() => ({
        currentViewId: [
            null as string | null,
            {
                persist: true,
                storageKey: `customerAnalytics.accounts.accountsViewsLogic.${getCurrentTeamId()}.currentViewId`,
            },
            {
                setCurrentViewId: (_, { id }) => id,
                deleteViewSuccess: (state, { views }) => (state && !views.find((v) => v.id === state) ? null : state),
            },
        ],
        isCreating: [
            false,
            {
                setIsCreating: (_, { isCreating }) => isCreating,
                submitNewViewFormSuccess: () => false,
            },
        ],
        viewToDelete: [
            null as string | null,
            {
                setViewToDelete: (_, { id }) => id,
            },
        ],
    })),
    selectors({
        liveViewState: [
            (s) => [
                s.selectColumns,
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.csmFilter,
                s.accountExecutiveFilter,
                s.accountOwnerFilter,
                s.sortOrder,
                s.tileFilter,
                s.tiles,
            ],
            (
                selectColumns,
                searchQuery,
                tagsFilter,
                allRolesUnassigned,
                csmFilter,
                accountExecutiveFilter,
                accountOwnerFilter,
                sortOrder,
                tileFilter,
                tiles
            ): AccountsViewState => ({
                columns: selectColumns,
                sortOrder,
                filters: {
                    search: searchQuery,
                    tags: tagsFilter,
                    unassigned: allRolesUnassigned,
                    csm: csmFilter,
                    accountExecutive: accountExecutiveFilter,
                    accountOwner: accountOwnerFilter,
                    tileFilter,
                },
                tiles,
            }),
        ],
        currentView: [
            (s) => [s.views, s.currentViewId],
            (views, currentViewId): ColumnConfigurationApi | null =>
                views.find((view) => view.id === currentViewId) ?? null,
        ],
        isDirty: [
            (s) => [s.currentView, s.liveViewState],
            (currentView, liveViewState): boolean =>
                currentView
                    ? !objectsEqual(
                          serializeAccountsView(deserializeAccountsView(currentView)),
                          serializeAccountsView(liveViewState)
                      )
                    : false,
        ],
        canEditCurrentView: [
            (s) => [s.currentView, s.user],
            (currentView, user): boolean => !!currentView && !!user && currentView.created_by === user.id,
        ],
    }),
    forms(({ actions, values }) => ({
        newViewForm: {
            defaults: { name: '', visibility: 'private' as ViewVisibility },
            errors: ({ name }: { name: string }) => ({ name: !name?.trim() ? 'Name is required' : undefined }),
            submit: async ({ name, visibility }: { name: string; visibility: ViewVisibility }) => {
                const response = await api.columnConfigurations.create({
                    data: {
                        ...serializeAccountsView(values.liveViewState),
                        context_key: ACCOUNTS_COLUMN_CONFIG_KEY,
                        name: name.trim(),
                        visibility,
                    },
                })
                actions.loadViews()
                actions.applyView(response)
                actions.resetNewViewForm()
                posthog.capture(AccountsEvents.ViewSaved, { visibility })
            },
        },
    })),
    listeners(({ actions, values }) => ({
        selectView: ({ id }) => {
            const view = values.views.find((v) => v.id === id)
            if (view) {
                actions.applyView(view)
            }
        },
        applyView: ({ view }) => {
            const state = deserializeAccountsView(view)
            actions.setSelectColumns(state.columns)
            actions.setSearchQuery(state.filters.search)
            actions.setTagsFilter(state.filters.tags)
            // accountsLogic cross-clears role filters vs "unassigned only", so set the
            // unassigned flag first so the role filters below aren't wiped by that cross-listener.
            actions.setAllRolesUnassigned(state.filters.unassigned)
            actions.setCsmFilter(state.filters.csm)
            actions.setAccountExecutiveFilter(state.filters.accountExecutive)
            actions.setAccountOwnerFilter(state.filters.accountOwner)
            actions.setSortOrder(state.sortOrder)
            actions.setTiles(state.tiles)
            actions.setTileFilter(state.filters.tileFilter)
            actions.setCurrentViewId(view.id)
            posthog.capture(AccountsEvents.ViewSelected, { visibility: view.visibility })
        },
        updateViewSuccess: () => {
            lemonToast.success('View updated')
            posthog.capture(AccountsEvents.ViewUpdated)
        },
        updateViewFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to update view')
        },
        deleteViewSuccess: () => {
            lemonToast.success('View deleted')
            posthog.capture(AccountsEvents.ViewDeleted)
        },
        deleteViewFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to delete view')
        },
        loadViewsFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to load views')
        },
        submitNewViewFormFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to save view')
        },
        patchViewPropertiesFailure: ({ error }) => {
            // Silent background migration — no toast, just capture the exception.
            posthog.captureException(error)
        },
        loadViewsSuccess: ({ views }) => {
            if (!objectsEqual(values.tiles, DEFAULT_TILES)) {
                const candidate = views.find(
                    (view) =>
                        view.created_by === values.user?.id &&
                        !(view.properties as AccountsViewProperties | undefined)?.tiles?.length
                )
                if (candidate) {
                    actions.patchViewProperties({ id: candidate.id, properties: { tiles: values.tiles } })
                }
            }

            const hashHasView = !!router.values.hashParams?.view
            if (values.currentViewId && !hashHasView) {
                const view = views.find((v) => v.id === values.currentViewId)
                if (view) {
                    actions.applyView(view)
                }
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadViews()
    }),
])
