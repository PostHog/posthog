import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api, { PaginatedResponse } from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { objectClean, objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { tagsModel } from '~/models/tagsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb, DashboardBasicType } from '~/types'

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
    createdBy: number[] | 'All users'
    pinned: boolean
    starred: boolean
    shared: boolean
    tags?: string[]
    /** Folder path to filter to, e.g. 'Unfiled/Dashboards' (empty string = project root). null means no folder filter. */
    folder?: string | null
}

export const DEFAULT_FILTERS: DashboardsFilters = {
    search: '',
    createdBy: 'All users',
    pinned: false,
    starred: false,
    shared: false,
    tags: [],
    folder: null,
}

/** Router may coerce numeric-looking query values to numbers; search text must stay a string. */
function urlSearchParamToString(value: unknown): string {
    return `${value ?? ''}`
}

export const dashboardsLogic = kea<dashboardsLogicType>([
    path(['scenes', 'dashboard', 'dashboardsLogic']),
    connect(() => ({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags'], tagsModel, ['tags']],
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
        toggleStarredDashboard: (id: number, name: string) => ({ id, name }),
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
                setSearch: (state, { search }) => ({ ...state, search }),
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
                 * Server-side fuzzy search via the dashboards list endpoint. Returns null when
                 * there's no active search term, in which case the dashboards selector falls
                 * back to the in-memory `dashboardsModel` list.
                 *
                 * The 250ms `breakpoint` runs before the empty-term short-circuit so a stale
                 * in-flight request can't clobber a freshly cleared search.
                 */
                loadSearchedDashboards: async (
                    { search, tags, folder }: { search: string; tags: string[]; folder: string | null },
                    breakpoint
                ) => {
                    await breakpoint(250)
                    const term = search.trim()
                    if (!term) {
                        return null
                    }
                    const teamId = teamLogic.values.currentTeamId
                    if (teamId == null) {
                        return null
                    }
                    const params = new URLSearchParams({
                        search: term,
                        limit: '200',
                        exclude_generated: 'true',
                    })
                    // Push tag/folder filtering to the server so MCP and API clients see the same
                    // result shape as the UI, and so the limit:200 cap operates on the right
                    // population — filtered first, not after. Without this, a folder filter combined
                    // with search would only narrow the top-200 global matches and silently drop the rest.
                    for (const tag of tags) {
                        params.append('tags', tag)
                    }
                    if (folder != null) {
                        params.append('folder', folder)
                    }
                    const response: PaginatedResponse<DashboardBasicType> = await api.get(
                        `api/environments/${teamId}/dashboards/?${params.toString()}`
                    )
                    breakpoint()
                    return response.results ?? []
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
        // Starring reuses the file-system "shortcuts" feature: a starred dashboard has a
        // FileSystemShortcut row (per-user) whose `ref` is the dashboard id. Project the canonical
        // `shortcutByTypeRef` map down to the set of starred dashboard ids for the list filter and
        // the per-row star icon.
        starredDashboardRefs: [
            () => [projectTreeDataLogic.selectors.shortcutByTypeRef],
            (shortcutByTypeRef): Set<string> =>
                new Set(
                    Object.values(shortcutByTypeRef)
                        .filter((shortcut) => shortcut.type === 'dashboard' && shortcut.ref)
                        .map((shortcut) => shortcut.ref as string)
                ),
        ],
        // True while the user has the Starred filter on but their shortcuts haven't loaded yet.
        // Without this, a bookmarked `?starred=true` would filter every dashboard out (shortcutData
        // starts empty and loads async) and look broken — so we hold the table in a loading state instead.
        starredFilterPending: [
            (s) => [s.filters, projectTreeDataLogic.selectors.shortcutDataHasLoaded],
            (filters, shortcutDataHasLoaded): boolean => filters.starred === true && !shortcutDataHasLoaded,
        ],
        dashboards: [
            (s) => [
                dashboardsModel.selectors.nameSortedDashboards,
                dashboardsModel.selectors.rawDashboards,
                s.searchedDashboards,
                s.filters,
                s.currentTab,
                s.user,
                s.starredDashboardRefs,
                projectTreeDataLogic.selectors.shortcutDataHasLoaded,
            ],
            (
                allDashboards,
                rawDashboards,
                searchedDashboards,
                filters,
                currentTab,
                user,
                starredDashboardRefs,
                shortcutDataHasLoaded
            ) => {
                // When a search term is active we trust the server's trigram word similarity
                // ranking; otherwise we use the model's alphabetised list. This keeps the exact
                // match at the top.
                //
                // For the search branch we re-hydrate each row from `rawDashboards` so that
                // pin/unpin/rename mutations driven by `dashboardsModel` show up immediately
                // in the search results — without this, `searchedDashboards` would freeze at
                // the API response state until the next refetch.
                let haystack: DashboardBasicType[] =
                    filters.search && searchedDashboards
                        ? searchedDashboards.map((d) => (rawDashboards[d.id] as DashboardBasicType | undefined) ?? d)
                        : allDashboards
                if (currentTab === DashboardsTab.Pinned) {
                    haystack = haystack.filter((d) => d.pinned)
                }
                if (filters.pinned) {
                    haystack = haystack.filter((d) => d.pinned)
                }
                // Only narrow to starred once shortcuts have loaded — otherwise the set is still empty
                // and we'd wrongly hide everything (the table shows a loading state via starredFilterPending).
                if (filters.starred && shortcutDataHasLoaded) {
                    haystack = haystack.filter((d) => starredDashboardRefs.has(String(d.id)))
                }
                if (filters.shared) {
                    haystack = haystack.filter((d) => d.is_shared)
                }
                if (currentTab === DashboardsTab.Yours) {
                    haystack = haystack.filter((d) => d.created_by?.uuid === user?.uuid)
                } else if (filters.createdBy !== 'All users') {
                    const createdByIds = filters.createdBy
                    haystack = haystack.filter((d) => d.created_by != null && createdByIds.includes(d.created_by.id))
                }
                if (filters.tags && filters.tags.length > 0) {
                    haystack = haystack.filter((d) => filters.tags?.some((tag) => d.tags?.includes(tag)))
                }
                if (filters.folder != null) {
                    haystack = haystack.filter((d) => d.folder === filters.folder)
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
    trackedActionToUrl(({ values }) => ({
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
        setFilters: () => {
            const { createdBy, pinned, starred, shared, tags } = values.filters
            const searchParams: Record<string, any> = { ...router.values.searchParams }

            if (createdBy !== DEFAULT_FILTERS.createdBy) {
                searchParams['created_by'] = createdBy
            } else {
                delete searchParams['created_by']
            }
            if (pinned) {
                searchParams['pinned'] = true
            } else {
                delete searchParams['pinned']
            }
            if (starred) {
                searchParams['starred'] = true
            } else {
                delete searchParams['starred']
            }
            if (shared) {
                searchParams['shared'] = true
            } else {
                delete searchParams['shared']
            }
            if (tags && tags.length > 0) {
                searchParams['tags'] = tags
            } else {
                delete searchParams['tags']
            }

            // Persist the folder filter so it survives reloads/sharing. `null` means no filter (param absent);
            // an empty string is a valid value (project root), so we key off the param's presence, not its value.
            const folder = values.filters.folder ?? null
            if (folder === null) {
                delete searchParams['folder']
            } else {
                searchParams['folder'] = folder
            }

            if (objectsEqual(searchParams, router.values.searchParams)) {
                return
            }

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/dashboard': (_, searchParams) => {
            const tab = (searchParams['tab'] as DashboardsTab | undefined) || DashboardsTab.All
            if (values.currentTab !== tab) {
                actions.setCurrentTab(tab)
            }

            // Apply non-search filters before search so the setSearch listener's server fetch
            // sees the freshly-restored tags. Guard each dispatch on a real change so that the
            // actionToUrl -> locationChanged -> urlToAction round trip doesn't re-fire listeners
            // (e.g. a redundant server search) for filters that didn't actually move.
            const createdByParam = searchParams['created_by']
            const createdByIds = Array.isArray(createdByParam)
                ? createdByParam.map(Number).filter((id) => !Number.isNaN(id))
                : typeof createdByParam === 'number'
                  ? [createdByParam]
                  : []
            const nextFilters = {
                createdBy: createdByIds.length > 0 ? createdByIds : DEFAULT_FILTERS.createdBy,
                pinned: searchParams['pinned'] === true || searchParams['pinned'] === 'true',
                starred: searchParams['starred'] === true || searchParams['starred'] === 'true',
                shared: searchParams['shared'] === true || searchParams['shared'] === 'true',
                tags: Array.isArray(searchParams['tags']) ? searchParams['tags'] : DEFAULT_FILTERS.tags,
                folder: 'folder' in searchParams ? urlSearchParamToString(searchParams['folder']) : null,
            }
            const current = values.filters
            if (
                !objectsEqual(current.createdBy, nextFilters.createdBy) ||
                current.pinned !== nextFilters.pinned ||
                current.starred !== nextFilters.starred ||
                current.shared !== nextFilters.shared ||
                !objectsEqual(current.tags ?? [], nextFilters.tags ?? []) ||
                (current.folder ?? null) !== nextFilters.folder
            ) {
                actions.setFilters(nextFilters)
            }

            const search = urlSearchParamToString(searchParams['search'])
            if (values.filters.search !== search) {
                actions.setSearch(search)
            }
        },
    })),
    listeners(({ actions, values }) => ({
        setSearch: ({ search }) => {
            actions.loadSearchedDashboards({
                search,
                tags: values.filters.tags ?? [],
                folder: values.filters.folder ?? null,
            })
        },
        setFilters: ({ filters }) => {
            // Tag/folder changes refetch when a search is active so server-side filtering stays
            // accurate. Other filter keys (pinned/shared/createdBy/currentTab) are still
            // applied client-side over the in-memory list so they don't refetch.
            if (('tags' in filters || 'folder' in filters) && values.filters.search) {
                actions.loadSearchedDashboards({
                    search: values.filters.search,
                    tags: values.filters.tags ?? [],
                    folder: values.filters.folder ?? null,
                })
            }
        },
        toggleStarredDashboard: ({ id, name }) => {
            // Star/unstar a dashboard via the file-system shortcuts feature. If a shortcut already
            // exists, remove it; otherwise create one — preferring the real tree entry when it's
            // loaded, falling back to a minimal entry built from the row.
            const existing = projectTreeDataLogic.values.shortcutByTypeRef[`dashboard::${id}`]
            if (existing?.id) {
                projectTreeDataLogic.actions.deleteShortcut(existing.id)
                return
            }
            const entry: FileSystemEntry = projectTreeDataLogic.values.itemsByRef[`dashboard::${id}`] ?? {
                id: `dashboard::${id}`,
                path: name || 'Untitled',
                type: 'dashboard',
                ref: String(id),
                href: urls.dashboard(id),
            }
            projectTreeDataLogic.actions.addShortcutItem(entry, 'dashboards_list')
        },
    })),
])
