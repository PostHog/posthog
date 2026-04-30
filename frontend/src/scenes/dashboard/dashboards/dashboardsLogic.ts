import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api, { PaginatedResponse } from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { listSelectionLogic } from 'lib/logic/listSelectionLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { objectClean } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { tagsModel } from '~/models/tagsModel'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { ActivityScope, Breadcrumb, DashboardBasicType, DashboardType } from '~/types'

import type { dashboardsLogicType } from './dashboardsLogicType'

export enum DashboardsTab {
    All = 'all',
    Yours = 'yours',
    Pinned = 'pinned',
    Templates = 'templates',
}

const DEFAULT_SORTING: Sorting = { columnKey: 'name', order: 1 }

export interface DashboardsFilters {
    search: string
    createdBy: string
    pinned: boolean
    shared: boolean
    tags?: string[]
}

export const DEFAULT_FILTERS: DashboardsFilters = {
    search: '',
    createdBy: 'All users',
    pinned: false,
    shared: false,
    tags: [],
}

/** Router may coerce numeric-looking query values to numbers; search text must stay a string. */
function urlSearchParamToString(value: unknown): string {
    return `${value ?? ''}`
}

export const dashboardsLogic = kea<dashboardsLogicType>([
    path(['scenes', 'dashboard', 'dashboardsLogic']),
    tabAwareScene(),
    connect(() => ({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags'], tagsModel, ['tags']],
        actions: [listSelectionLogic({ resource: 'dashboards' }), ['bulkUpdateTagsSuccess']],
    })),
    actions({
        setCurrentTab: (tab: DashboardsTab) => ({ tab }),
        setSearch: (search: string) => ({ search }),
        setFilters: (filters: Partial<DashboardsFilters>) => ({
            filters,
        }),
        tableSortingChanged: (sorting: Sorting | null) => ({
            sorting,
        }),
        setTagSearch: (search: string) => ({ search }),
        setShowTagPopover: (visible: boolean) => ({ visible }),
    }),
    reducers({
        tableSorting: [
            DEFAULT_SORTING,
            { persist: true },
            {
                tableSortingChanged: (_, { sorting }) => sorting || DEFAULT_SORTING,
            },
        ],
        currentTab: [
            DashboardsTab.All as DashboardsTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],

        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) =>
                    objectClean({
                        ...state,
                        ...filters,
                    }),
            },
        ],
        tagSearch: [
            '',
            {
                setTagSearch: (_, { search }) => search,
                setShowTagPopover: (state, { visible }) => (visible ? state : ''),
            },
        ],
        showTagPopover: [
            false,
            {
                setShowTagPopover: (_, { visible }) => visible,
            },
        ],
    }),

    loaders({
        searchedDashboards: [
            null as DashboardBasicType[] | null,
            {
                /**
                 * Server-side fuzzy full-text search via the dashboards list endpoint.
                 * Returns null when there's no active search term, in which case the
                 * dashboards selector falls back to the in-memory `dashboardsModel` list.
                 */
                loadSearchedDashboards: async ({ search }: { search: string }, breakpoint) => {
                    const term = search.trim()
                    if (!term) {
                        return null
                    }
                    const teamId = teamLogic.values.currentTeamId
                    if (teamId == null) {
                        return null
                    }
                    // 250ms debounce so we don't fire a request on every keystroke.
                    await breakpoint(250)
                    const params = new URLSearchParams({
                        search: term,
                        limit: '200',
                        exclude_generated: 'true',
                    })
                    const response: PaginatedResponse<DashboardType> = await api.get(
                        `api/environments/${teamId}/dashboards/?${params.toString()}`
                    )
                    breakpoint()
                    return (response.results ?? []).map(
                        (dashboard) => getQueryBasedDashboard(dashboard) as DashboardBasicType
                    )
                },
            },
        ],
    }),

    selectors({
        isFiltering: [
            (s) => [s.filters],
            (filters) => {
                return Object.keys(filters).some((key) => {
                    const filterKey = key as keyof DashboardsFilters
                    return filters[filterKey] !== DEFAULT_FILTERS[filterKey]
                })
            },
        ],
        filteredTags: [
            (s) => [s.tags, s.tagSearch],
            (tags, search) => {
                if (!search) {
                    return tags || []
                }
                return (tags || []).filter((tag) => tag.toLowerCase().includes(search.toLowerCase()))
            },
        ],
        dashboards: [
            (s) => [
                dashboardsModel.selectors.nameSortedDashboards,
                s.searchedDashboards,
                s.filters,
                s.currentTab,
                s.user,
            ],
            (allDashboards, searchedDashboards, filters, currentTab, user) => {
                // When a search term is active we trust the server's relevance ranking
                // (combined FTS rank + trigram similarity); otherwise we use the model's
                // alphabetised list. This keeps the exact match at the top of the list.
                let haystack: DashboardBasicType[] =
                    filters.search && searchedDashboards ? searchedDashboards : allDashboards
                if (currentTab === DashboardsTab.Pinned) {
                    haystack = haystack.filter((d) => d.pinned)
                }
                if (filters.pinned) {
                    haystack = haystack.filter((d) => d.pinned)
                }
                if (filters.shared) {
                    haystack = haystack.filter((d) => d.is_shared)
                }
                if (currentTab === DashboardsTab.Yours) {
                    haystack = haystack.filter((d) => d.created_by?.uuid === user?.uuid)
                } else if (filters.createdBy !== 'All users') {
                    haystack = haystack.filter((d) => d.created_by?.uuid === filters.createdBy)
                }
                if (filters.tags && filters.tags.length > 0) {
                    haystack = haystack.filter((d) => filters.tags?.some((tag) => d.tags?.includes(tag)))
                }
                return haystack
            },
        ],

        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'dashboards',
                    name: 'Dashboards',
                    iconType: 'dashboard',
                },
            ],
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.DASHBOARD,
            }),
        ],
    }),
    tabAwareActionToUrl(({ values }) => ({
        setCurrentTab: () => {
            const tab = values.currentTab === DashboardsTab.All ? undefined : values.currentTab
            if (router.values.searchParams['tab'] === tab) {
                return
            }

            router.actions.push(router.values.location.pathname, {
                ...router.values.searchParams,
                tab,
            })
        },
        setSearch: ({ search }) => {
            const nextSearch = search ?? ''
            const currentSearch = urlSearchParamToString(router.values.searchParams['search'])

            if (nextSearch === currentSearch) {
                return
            }

            const searchParams: Record<string, any> = {
                ...router.values.searchParams,
            }

            if (nextSearch) {
                searchParams['search'] = nextSearch
            } else {
                delete searchParams['search']
            }

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    })),
    tabAwareUrlToAction(({ actions }) => ({
        '/dashboard': (_, searchParams) => {
            const tab = (searchParams['tab'] as DashboardsTab | undefined) || DashboardsTab.All
            actions.setCurrentTab(tab)

            const search = urlSearchParamToString(searchParams['search'])
            actions.setFilters({ search })
        },
    })),
    listeners(({ actions, values }) => ({
        bulkUpdateTagsSuccess: () => {
            dashboardsModel.actions.loadDashboards()
        },
        setFilters: ({ filters }) => {
            // Only refetch when the search term itself changes; other filter changes are applied
            // client-side on top of the existing search results (or the in-memory list).
            if ('search' in filters) {
                actions.loadSearchedDashboards({ search: values.filters.search })
            }
        },
    })),
])
