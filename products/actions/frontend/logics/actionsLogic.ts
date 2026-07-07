import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import api, { CountedPaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils/objects'
import { toParams } from 'lib/utils/url'
import { DataManagementTab } from 'scenes/data-management/DataManagementScene'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActionType, ActivityScope, Breadcrumb } from '~/types'

import type { actionsLogicType } from './actionsLogicType'

export const ACTIONS_PER_PAGE = 50

export type ActionsResponse = CountedPaginatedResponse<ActionType>

export interface ActionsFilters {
    createdBy: number[]
    tags: string[]
    ordering: string
}

const DEFAULT_FILTERS: ActionsFilters = {
    createdBy: [],
    tags: [],
    ordering: '-created_by',
}

export const actionsLogic = kea<actionsLogicType>([
    path(['products', 'actions', 'actionsLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setFilters: (filters: Partial<ActionsFilters>) => ({ filters }),
        setPage: (page: number) => ({ page }),
    }),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setFilters: () => 1,
                setSearchTerm: () => 1,
            },
        ],
    }),
    loaders(({ values }) => ({
        actionsResponse: [
            { count: 0, results: [] } as ActionsResponse,
            {
                loadActions: async () => {
                    const response = await api.actions.list(values.apiParams)
                    return { count: response.count ?? 0, results: response.results ?? [] }
                },
                pinAction: async (action: ActionType) => {
                    const updated = await api.actions.update(action.id, {
                        name: action.name,
                        pinned_at: new Date().toISOString(),
                    })
                    return {
                        ...values.actionsResponse,
                        results: values.actionsResponse.results.map((a) => (a.id === updated.id ? updated : a)),
                    }
                },
                unpinAction: async (action: ActionType) => {
                    const updated = await api.actions.update(action.id, {
                        name: action.name,
                        pinned_at: null,
                    })
                    return {
                        ...values.actionsResponse,
                        results: values.actionsResponse.results.map((a) => (a.id === updated.id ? updated : a)),
                    }
                },
            },
        ],
    })),
    selectors({
        actionsList: [(s) => [s.actionsResponse], (response): ActionType[] => response.results],
        actionCount: [(s) => [s.actionsResponse], (response): number => response.count],
        apiParams: [
            (s) => [s.searchTerm, s.filters, s.page, s.featureFlags],
            (searchTerm, filters, page, featureFlags): string => {
                const params: Record<string, any> = {
                    limit: ACTIONS_PER_PAGE,
                    offset: (page - 1) * ACTIONS_PER_PAGE,
                    ordering: filters.ordering,
                    include_count: 1,
                }
                if (searchTerm.trim()) {
                    params.search = searchTerm.trim()
                }
                if (filters.createdBy.length > 0) {
                    params.created_by = filters.createdBy.join(',')
                }
                if (filters.tags.length > 0) {
                    params.tags = JSON.stringify(filters.tags)
                }
                if (featureFlags[FEATURE_FLAGS.ACTION_REFERENCE_COUNT]) {
                    params.include_reference_count = 1
                }
                return toParams(params)
            },
        ],
        hasActiveFilters: [
            (s) => [s.searchTerm, s.filters],
            (searchTerm, filters): boolean =>
                !!searchTerm.trim() || filters.createdBy.length > 0 || filters.tags.length > 0,
        ],
        shouldShowEmptyState: [
            (s) => [s.actionCount, s.actionsResponseLoading, s.hasActiveFilters],
            (actionCount: number, actionsResponseLoading: boolean, hasActiveFilters: boolean): boolean =>
                actionCount === 0 && !actionsResponseLoading && !hasActiveFilters,
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: DataManagementTab.Actions,
                    name: 'Actions',
                    path: urls.actions(),
                    iconType: 'action',
                },
            ],
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.ACTION,
            }),
        ],
    }),
    listeners(({ actions }) => ({
        setFilters: () => actions.loadActions(),
        setPage: () => actions.loadActions(),
        setSearchTerm: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadActions()
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.actions()]: (_, searchParams) => {
            const urlFilters: ActionsFilters = {
                ...DEFAULT_FILTERS,
                ...(searchParams.ordering !== undefined && { ordering: searchParams.ordering }),
                ...(Array.isArray(searchParams.tags) && { tags: searchParams.tags }),
                ...(Array.isArray(searchParams.created_by) && { createdBy: searchParams.created_by.map(Number) }),
            }
            if (!objectsEqual(values.filters, urlFilters)) {
                actions.setFilters(urlFilters)
            } else if (!values.actionsResponse.results.length && !values.actionsResponseLoading) {
                actions.loadActions()
            }
        },
    })),
    // Search term and page are intentionally not URL-synced; only the shareable filters are.
    actionToUrl(({ values }) => {
        const buildUrl = (): [string, Record<string, any>] => [
            urls.actions(),
            {
                ...(values.filters.ordering !== DEFAULT_FILTERS.ordering && { ordering: values.filters.ordering }),
                ...(values.filters.tags.length > 0 && { tags: values.filters.tags }),
                ...(values.filters.createdBy.length > 0 && { created_by: values.filters.createdBy }),
            },
        ]
        return {
            setFilters: buildUrl,
        }
    }),
])
