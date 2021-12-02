import { isBreakpoint, kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { router } from 'kea-router'
import { toast } from 'react-toastify'
import { clearDOMTextSelection, editingToast, setPageTitle, toParams } from 'lib/utils'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { ACTIONS_LINE_GRAPH_LINEAR, PATHS_VIZ } from 'lib/constants'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    Breadcrumb,
    DashboardItemType,
    DashboardLayoutSize,
    DashboardMode,
    DashboardType,
    FilterType,
    InsightShortId,
    InsightType,
} from '~/types'
import { dashboardLogicType } from './dashboardLogicType'
import React from 'react'
import { Layout, Layouts } from 'react-grid-layout'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'
import { getInsightId } from 'scenes/insights/utils'

export interface DashboardLogicProps {
    id?: number
    shareToken?: string
    internal?: boolean
}

export const AUTO_REFRESH_INITIAL_INTERVAL_SECONDS = 300

export const dashboardLogic = kea<dashboardLogicType<DashboardLogicProps>>({
    path: (key) => ['scenes', 'dashboard', 'dashboardLogic', key],
    connect: {
        values: [teamLogic, ['currentTeamId']],
        logic: [dashboardsModel, dashboardItemsModel, eventUsageLogic],
    },

    props: {} as DashboardLogicProps,

    key: (props) => props.id || 'dashboardLogic',

    actions: {
        setReceivedErrorsFromAPI: (receivedErrors: boolean) => ({
            receivedErrors,
        }),
        addNewDashboard: true,
        loadDashboardItems: ({
            refresh,
            dive_source_id,
        }: {
            refresh?: boolean
            dive_source_id?: InsightShortId
        } = {}) => ({
            refresh,
            dive_source_id,
        }),
        triggerDashboardUpdate: (payload) => ({ payload }),
        /** Whether the dashboard is shared or not. */
        setIsSharedDashboard: (id: number, isShared: boolean) => ({ id, isShared }),
        /** The current state in which the dashboard is being viewed, see DashboardMode. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource | null) => ({ mode, source }),
        updateLayouts: (layouts: Layouts) => ({ layouts }),
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        saveLayouts: true,
        updateItemColor: (insightId: number, color: string) => ({ insightId, color }),
        setDiveDashboard: (insightId: number, dive_dashboard: number | null) => ({ insightId, dive_dashboard }),
        refreshAllDashboardItems: (items?: DashboardItemType[]) => ({ items }),
        refreshAllDashboardItemsManual: true,
        resetInterval: true,
        updateAndRefreshDashboard: true,
        setDates: (dateFrom: string, dateTo: string | null, reloadDashboard = true) => ({
            dateFrom,
            dateTo,
            reloadDashboard,
        }),
        /** Take the user to insights to add a graph. */
        addGraph: true,
        deleteTag: (tag: string) => ({ tag }),
        saveNewTag: (tag: string) => ({ tag }),
        setAutoRefresh: (enabled: boolean, interval: number) => ({ enabled, interval }),
        setRefreshStatus: (shortId: InsightShortId, loading = false) => ({ shortId, loading }),
        setRefreshStatuses: (shortIds: InsightShortId[], loading = false) => ({ shortIds, loading }),
        setRefreshError: (shortId: InsightShortId) => ({ shortId }),
    },

    loaders: ({ actions, props }) => ({
        allItems: [
            null as DashboardType | null,
            {
                loadDashboardItems: async ({ refresh, dive_source_id }) => {
                    actions.setReceivedErrorsFromAPI(false)

                    if (!props.id) {
                        console.warn('Called `loadDashboardItems` but ID is not set.')
                        return
                    }

                    try {
                        const apiUrl = props.shareToken
                            ? `api/shared_dashboards/${props.shareToken}`
                            : `api/projects/${teamLogic.values.currentTeamId}/dashboards/${props.id}/?${toParams({
                                  refresh,
                                  dive_source_id: dive_source_id ? await getInsightId(dive_source_id) : undefined,
                              })}`
                        const dashboard = await api.get(apiUrl)
                        actions.setDates(dashboard.filters.date_from, dashboard.filters.date_to, false)
                        setPageTitle(dashboard.name ? `${dashboard.name} • Dashboard` : 'Dashboard')
                        eventUsageLogic.actions.reportDashboardViewed(dashboard, !!props.shareToken)
                        return dashboard
                    } catch (error) {
                        if (error.status === 404) {
                            return []
                        }
                        actions.setReceivedErrorsFromAPI(true)
                        throw error
                    }
                },
                updateDashboard: async (filters: Partial<FilterType>) => {
                    return await api.update(`api/projects/${teamLogic.values.currentTeamId}/dashboards/${props.id}`, {
                        filters,
                    })
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        receivedErrorsFromAPI: [
            false,
            {
                setReceivedErrorsFromAPI: (_: boolean, { receivedErrors }: { receivedErrors: boolean }) =>
                    receivedErrors,
            },
        ],
        filters: [
            { date_from: null, date_to: null } as FilterType,
            {
                setDates: (state, { dateFrom, dateTo }) => ({
                    ...state,
                    date_from: dateFrom || null,
                    date_to: dateTo || null,
                }),
            },
        ],
        allItems: [
            null as DashboardType | null,
            {
                [dashboardItemsModel.actionTypes.renameDashboardItemSuccess]: (state, { item }) => {
                    return {
                        ...state,
                        items: state?.items.map((i) => (i.short_id === item.short_id ? item : i)) || [],
                    } as DashboardType
                },
                updateLayouts: (state, { layouts }) => {
                    const itemLayouts: Record<string, Partial<Record<string, Layout>>> = {}
                    state?.items.forEach((item) => {
                        itemLayouts[item.short_id] = {}
                    })

                    Object.entries(layouts).forEach(([col, layout]) => {
                        layout.forEach((layoutItem) => {
                            if (!itemLayouts[layoutItem.i]) {
                                itemLayouts[layoutItem.i] = {}
                            }
                            itemLayouts[layoutItem.i][col] = layoutItem
                        })
                    })

                    return {
                        ...state,
                        items: state?.items.map((item) => ({ ...item, layouts: itemLayouts[item.short_id] })),
                    } as DashboardType
                },
                [dashboardsModel.actionTypes.updateDashboardItem]: (state, { item }) => {
                    return state
                        ? ({
                              ...state,
                              items: state?.items.map((i) => (i.short_id === item.short_id ? item : i)) || [],
                          } as DashboardType)
                        : null
                },
                [dashboardsModel.actionTypes.updateDashboardRefreshStatus]: (
                    state,
                    { shortId, refreshing, last_refresh }
                ) => {
                    // If not a dashboard item, don't do anything.
                    if (!shortId) {
                        return state
                    }
                    return {
                        ...state,
                        items: state?.items.map((i) =>
                            i.short_id === shortId
                                ? {
                                      ...i,
                                      ...(refreshing != null ? { refreshing } : {}),
                                      ...(last_refresh != null ? { last_refresh } : {}),
                                  }
                                : i
                        ),
                    } as DashboardType
                },
                updateItemColor: (state, { insightId, color }) => {
                    return {
                        ...state,
                        items: state?.items.map((i) => (i.id === insightId ? { ...i, color } : i)),
                    } as DashboardType
                },
                setDiveDashboard: (state, { insightId, dive_dashboard }) => {
                    return {
                        ...state,
                        items: state?.items.map((i) => (i.id === insightId ? { ...i, dive_dashboard } : i)),
                    } as DashboardType
                },
                [dashboardItemsModel.actionTypes.duplicateDashboardItemSuccess]: (state, { item }): DashboardType => {
                    return {
                        ...state,
                        items:
                            props.id && item.dashboard === parseInt(props.id.toString())
                                ? [...(state?.items || []), item]
                                : state?.items,
                    } as DashboardType
                },
            },
        ],
        refreshStatus: [
            {} as Record<
                string,
                {
                    loading?: boolean
                    refreshed?: boolean
                    error?: boolean
                }
            >,
            {
                setRefreshStatus: (state, { shortId, loading }) => ({
                    ...state,
                    [shortId]: loading ? { loading: true } : { refreshed: true },
                }),
                setRefreshStatuses: (_, { shortIds, loading }) =>
                    Object.fromEntries(
                        shortIds.map((shortId) => [shortId, loading ? { loading: true } : { refreshed: true }])
                    ) as Record<
                        string,
                        {
                            loading?: boolean
                            refreshed?: boolean
                            error?: boolean
                        }
                    >,
                setRefreshError: (state, { shortId }) => ({
                    ...state,
                    [shortId]: { error: true },
                }),
                refreshAllDashboardItems: () => ({}),
            },
        ],
        columns: [
            null as number | null,
            {
                updateContainerWidth: (_, { columns }) => columns,
            },
        ],
        containerWidth: [
            null as number | null,
            {
                updateContainerWidth: (_, { containerWidth }) => containerWidth,
            },
        ],
        dashboardMode: [
            null as DashboardMode | null,
            {
                setDashboardMode: (_, { mode }) => mode,
            },
        ],
        lastDashboardModeSource: [
            null as DashboardEventSource | null,
            {
                setDashboardMode: (_, { source }) => source,
            },
        ],
        autoRefresh: [
            {
                interval: AUTO_REFRESH_INITIAL_INTERVAL_SECONDS,
                enabled: false,
            } as {
                interval: number
                enabled: boolean
            },
            {
                setAutoRefresh: (_, { enabled, interval }) => ({ enabled, interval }),
            },
        ],
    }),
    selectors: ({ props, selectors }) => ({
        items: [() => [selectors.allItems], (allItems) => allItems?.items?.filter((i) => !i.deleted)],
        itemsLoading: [
            () => [selectors.allItemsLoading, selectors.refreshStatus],
            (allItemsLoading, refreshStatus) => {
                return allItemsLoading || Object.values(refreshStatus).some((s) => s.loading)
            },
        ],
        isRefreshing: [
            () => [selectors.refreshStatus],
            (refreshStatus) => (id: string) => !!refreshStatus[id]?.loading,
        ],
        highlightedInsightId: [
            () => [router.selectors.searchParams],
            (searchParams) => searchParams.highlightInsightId || searchParams.dive_source_id,
        ],
        lastRefreshed: [
            () => [selectors.items],
            (items) => {
                if (!items || !items.length) {
                    return null
                }
                let lastRefreshed = items[0].last_refresh

                for (const item of items) {
                    if (item.last_refresh < lastRefreshed) {
                        lastRefreshed = item.last_refresh
                    }
                }

                return lastRefreshed
            },
        ],
        dashboard: [
            () => [dashboardsModel.selectors.sharedDashboard, dashboardsModel.selectors.nameSortedDashboards],
            (sharedDashboard, dashboards): DashboardType | null => {
                return props.shareToken ? sharedDashboard : dashboards.find((d) => d.id === props.id) || null
            },
        ],
        breakpoints: [() => [], () => ({ lg: 1600, sm: 940, xs: 480, xxs: 0 } as Record<DashboardLayoutSize, number>)],
        cols: [() => [], () => ({ lg: 24, sm: 12, xs: 6, xxs: 2 } as Record<DashboardLayoutSize, number>)],
        sizeKey: [
            (s) => [s.columns, s.cols],
            (columns, cols): DashboardLayoutSize | undefined => {
                const [size] = (Object.entries(cols).find(([, value]) => value === columns) || []) as [
                    DashboardLayoutSize,
                    number
                ]
                return size
            },
        ],
        layouts: [
            () => [selectors.items, selectors.cols],
            (items, cols) => {
                const allLayouts: Partial<Record<keyof typeof cols, Layout[]>> = {}
                ;(Object.keys(cols) as (keyof typeof cols)[]).forEach((col) => {
                    const layouts = items
                        ?.filter((i) => !i.deleted)
                        .map((item) => {
                            const isRetention =
                                item.filters.insight === InsightType.RETENTION &&
                                item.filters.display === ACTIONS_LINE_GRAPH_LINEAR
                            const defaultWidth = isRetention || item.filters.display === PATHS_VIZ ? 8 : 6
                            const defaultHeight = isRetention ? 8 : item.filters.display === PATHS_VIZ ? 12.5 : 5
                            const layout = item.layouts && item.layouts[col]
                            const { x, y, w, h } = layout || {}
                            const width = Math.min(w || defaultWidth, cols[col])
                            return {
                                i: item.short_id,
                                x: Number.isInteger(x) && x + width - 1 < cols[col] ? x : 0,
                                y: Number.isInteger(y) ? y : Infinity,
                                w: width,
                                h: h || defaultHeight,
                            }
                        })

                    const cleanLayouts = layouts?.filter(({ y }) => y !== Infinity)

                    // array of -1 for each column
                    const lowestPoints = Array.from(Array(cols[col])).map(() => -1)

                    // set the lowest point for each column
                    cleanLayouts?.forEach(({ x, y, w, h }) => {
                        for (let i = x; i <= x + w - 1; i++) {
                            lowestPoints[i] = Math.max(lowestPoints[i], y + h - 1)
                        }
                    })

                    layouts
                        ?.filter(({ y }) => y === Infinity)
                        .forEach(({ i, w, h }) => {
                            // how low are things in "w" consecutive of columns
                            const segmentCount = cols[col] - w + 1
                            const lowestSegments = Array.from(Array(segmentCount)).map(() => -1)
                            for (let k = 0; k < segmentCount; k++) {
                                for (let j = k; j <= k + w - 1; j++) {
                                    lowestSegments[k] = Math.max(lowestSegments[k], lowestPoints[j])
                                }
                            }

                            let lowestIndex = 0
                            let lowestDepth = lowestSegments[0]

                            lowestSegments.forEach((depth, index) => {
                                if (depth < lowestDepth) {
                                    lowestIndex = index
                                    lowestDepth = depth
                                }
                            })

                            cleanLayouts?.push({
                                i,
                                x: lowestIndex,
                                y: lowestDepth + 1,
                                w,
                                h,
                            })

                            for (let k = lowestIndex; k <= lowestIndex + w - 1; k++) {
                                lowestPoints[k] = Math.max(lowestPoints[k], lowestDepth + h)
                            }
                        })

                    allLayouts[col] = cleanLayouts
                })
                return allLayouts
            },
        ],
        layout: [(s) => [s.layouts, s.sizeKey], (layouts, sizeKey) => (sizeKey ? layouts[sizeKey] : undefined)],
        layoutForItem: [
            (s) => [s.layout],
            (layout) => {
                const layoutForItem: Record<string, Layout> = {}
                if (layout) {
                    for (const obj of layout) {
                        layoutForItem[obj.i] = obj
                    }
                }
                return layoutForItem
            },
        ],
        refreshMetrics: [
            (s) => [s.refreshStatus],
            (refreshStatus) => {
                const total = Object.keys(refreshStatus).length ?? 0
                return {
                    completed: total - (Object.values(refreshStatus).filter((s) => s.loading).length ?? 0),
                    total,
                }
            },
        ],
        breadcrumbs: [
            (s) => [s.allItems],
            (allItems): Breadcrumb[] => [
                {
                    name: 'Dashboards',
                    path: urls.dashboards(),
                },
                {
                    name: allItems?.id ? allItems.name || 'Unnamed' : null,
                },
            ],
        ],
    }),
    events: ({ actions, cache, props }) => ({
        afterMount: () => {
            if (props.id) {
                // When the scene is initially loaded, the dashboard ID is undefined
                actions.loadDashboardItems({
                    refresh: props.internal,
                    dive_source_id: dashboardsModel.values.diveSourceId ?? undefined,
                })
            }

            if (props.shareToken) {
                actions.setDashboardMode(
                    props.internal ? DashboardMode.Internal : DashboardMode.Public,
                    DashboardEventSource.Browser
                )
                dashboardsModel.actions.loadSharedDashboard(props.shareToken)
            }
        },
        beforeUnmount: () => {
            if (cache.draggingToastId) {
                toast.dismiss(cache.draggingToastId)
                cache.draggingToastId = null
            }

            if (cache.autoRefreshInterval) {
                window.clearInterval(cache.autoRefreshInterval)
                cache.autoRefreshInterval = null
            }
        },
    }),
    listeners: ({ actions, values, key, cache }) => ({
        addNewDashboard: async () => {
            prompt({ key: `new-dashboard-${key}` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: (name: string) => dashboardsModel.actions.addDashboard({ name }),
            })
        },
        [dashboardsModel.actionTypes.addDashboardSuccess]: ({ dashboard }) => {
            router.actions.push(`/dashboard/${dashboard.id}`)
        },
        setIsSharedDashboard: ({ id, isShared }) => {
            dashboardsModel.actions.setIsSharedDashboard({ id, isShared })
            eventUsageLogic.actions.reportDashboardShareToggled(isShared)
        },
        triggerDashboardUpdate: ({ payload }) => {
            if (values.dashboard) {
                dashboardsModel.actions.updateDashboard({ id: values.dashboard.id, ...payload })
            }
        },
        updateLayouts: () => {
            actions.saveLayouts()
        },
        saveLayouts: async (_, breakpoint) => {
            await breakpoint(300)
            await api.update(`api/projects/${values.currentTeamId}/insights/layouts`, {
                items:
                    values.items?.map((item) => {
                        const layouts: Record<string, Layout> = {}
                        Object.entries(item.layouts).forEach(([layoutKey, layout]) => {
                            const { i, ...rest } = layout // eslint-disable-line
                            layouts[layoutKey] = rest
                        })
                        return { id: item.id, layouts }
                    }) || [],
            })
        },
        updateItemColor: async ({ insightId, color }) => {
            return api.update(`api/projects/${values.currentTeamId}/insights/${insightId}`, { color })
        },
        setDiveDashboard: async ({ insightId, dive_dashboard }) => {
            return api.update(`api/projects/${values.currentTeamId}/insights/${insightId}`, { dive_dashboard })
        },
        refreshAllDashboardItemsManual: () => {
            // reset auto refresh interval
            actions.resetInterval()
            actions.refreshAllDashboardItems()
        },
        refreshAllDashboardItems: async ({ items: _items }, breakpoint) => {
            const items = _items || values.items || []

            // Don't do anything if there's nothing to refresh
            if (items.length === 0) {
                return
            }

            let breakpointTriggered = false
            actions.setRefreshStatuses(
                items.map((item) => item.short_id),
                true
            )

            // array of functions that reload each item
            const fetchItemFunctions = items.map((dashboardItem) => async () => {
                try {
                    breakpoint()

                    const refreshedDashboardItem = await api.get(
                        `api/projects/${values.currentTeamId}/insights/${dashboardItem.id}/?${toParams({
                            refresh: true,
                        })}`
                    )
                    breakpoint()

                    // reload the cached results inside the insight's logic
                    if (dashboardItem.filters.insight) {
                        const itemResultLogic = insightLogic({
                            dashboardItemId: dashboardItem.short_id,
                            filters: dashboardItem.filters,
                            cachedResults: refreshedDashboardItem.result,
                        })
                        itemResultLogic.actions.setInsight(
                            { ...dashboardItem, result: refreshedDashboardItem.result },
                            { fromPersistentApi: true }
                        )
                    }

                    dashboardsModel.actions.updateDashboardItem(refreshedDashboardItem)
                    actions.setRefreshStatus(dashboardItem.short_id)
                } catch (e) {
                    if (isBreakpoint(e)) {
                        breakpointTriggered = true
                    } else {
                        actions.setRefreshError(dashboardItem.short_id)
                    }
                }
            })

            // run 4 item reloaders in parallel
            function loadNextPromise(): void {
                if (!breakpointTriggered && fetchItemFunctions.length > 0) {
                    fetchItemFunctions.shift()?.().then(loadNextPromise)
                }
            }
            for (let i = 0; i < 4; i++) {
                void loadNextPromise()
            }

            eventUsageLogic.actions.reportDashboardRefreshed(values.lastRefreshed)
        },
        updateAndRefreshDashboard: async (_, breakpoint) => {
            await breakpoint(200)
            actions.updateDashboard(values.filters)
            actions.refreshAllDashboardItems()
        },
        setDates: ({ dateFrom, dateTo, reloadDashboard }) => {
            if (reloadDashboard) {
                actions.updateAndRefreshDashboard()
            }
            eventUsageLogic.actions.reportDashboardDateRangeChanged(dateFrom, dateTo)
        },
        setDashboardMode: async ({ mode, source }) => {
            // Edit mode special handling
            if (mode === DashboardMode.Fullscreen) {
                document.body.classList.add('fullscreen-scroll')
            } else {
                document.body.classList.remove('fullscreen-scroll')
            }
            if (mode === DashboardMode.Edit) {
                clearDOMTextSelection()

                if (!cache.draggingToastId) {
                    cache.draggingToastId = editingToast('Dashboard', actions.setDashboardMode)
                }
            } else {
                // Clean edit mode toast if applicable
                if (cache.draggingToastId) {
                    toast.dismiss(cache.draggingToastId)
                    cache.draggingToastId = null
                }
            }

            if (mode) {
                eventUsageLogic.actions.reportDashboardModeToggled(mode, source)
            }
        },
        addGraph: () => {
            if (values.dashboard) {
                router.actions.push(urls.insightNew({ insight: InsightType.TRENDS }))
            }
        },
        saveNewTag: ({ tag }) => {
            if (values.dashboard?.tags.includes(tag)) {
                toast.error(
                    // TODO: move to errorToast once #3561 is merged
                    <div>
                        <h1>Oops! Can't add that tag</h1>
                        <p>Your dashboard already has that tag.</p>
                    </div>
                )
                return
            }
            actions.triggerDashboardUpdate({ tags: [...(values.dashboard?.tags || []), tag] })
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            actions.triggerDashboardUpdate({ tags: values.dashboard?.tags.filter((_tag) => _tag !== tag) || [] })
        },
        setAutoRefresh: () => {
            actions.resetInterval()
        },
        resetInterval: () => {
            if (cache.autoRefreshInterval) {
                window.clearInterval(cache.autoRefreshInterval)
                cache.autoRefreshInterval = null
            }

            if (values.autoRefresh.enabled) {
                cache.autoRefreshInterval = window.setInterval(() => {
                    actions.refreshAllDashboardItems()
                }, values.autoRefresh.interval * 1000)
            }
        },
        loadDashboardItemsSuccess: () => {
            // Initial load of actual data for dashboard items after general dashboard is fetched
            const notYetLoadedItems = values.allItems?.items?.filter((i) => !i.result)
            actions.refreshAllDashboardItems(notYetLoadedItems)
        },
    }),
})
