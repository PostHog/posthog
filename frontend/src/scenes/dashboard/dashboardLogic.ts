import { isBreakpoint, kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { dayjs, now } from 'lib/dayjs'
import { clearDOMTextSelection, isUserLoggedIn, toParams } from 'lib/utils'
import { insightsModel } from '~/models/insightsModel'
import { DashboardPrivilegeLevel, FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    AnyPropertyFilter,
    Breadcrumb,
    ChartDisplayType,
    DashboardLayoutSize,
    DashboardMode,
    DashboardPlacement,
    DashboardType,
    FilterType,
    InsightModel,
    InsightShortId,
    InsightType,
} from '~/types'
import type { dashboardLogicType } from './dashboardLogicType'
import { Layout, Layouts } from 'react-grid-layout'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { mergeWithDashboardTile } from 'scenes/insights/utils/dashboardTiles'

export const BREAKPOINTS: Record<DashboardLayoutSize, number> = {
    sm: 1024,
    xs: 0,
}
export const BREAKPOINT_COLUMN_COUNTS: Record<DashboardLayoutSize, number> = { sm: 12, xs: 1 }
export const MIN_ITEM_WIDTH_UNITS = 3
export const MIN_ITEM_HEIGHT_UNITS = 5

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export interface DashboardLogicProps {
    id?: number
    shareToken?: string
    placement?: DashboardPlacement
}

export const AUTO_REFRESH_INITIAL_INTERVAL_SECONDS = 300

export const dashboardLogic = kea<dashboardLogicType>({
    path: ['scenes', 'dashboard', 'dashboardLogic'],
    connect: () => ({
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
        logic: [dashboardsModel, insightsModel, eventUsageLogic],
    }),

    props: {} as DashboardLogicProps,

    key: (props) => {
        if (typeof props.id === 'string') {
            throw Error('Must init dashboardLogic with a numeric key')
        }
        return props.id ?? 'new'
    },

    actions: {
        setReceivedErrorsFromAPI: (receivedErrors: boolean) => ({
            receivedErrors,
        }),
        loadDashboardItems: ({
            refresh,
        }: {
            refresh?: boolean
        } = {}) => ({
            refresh,
        }),
        triggerDashboardUpdate: (payload) => ({ payload }),
        /** Whether the dashboard is shared or not. */
        setIsSharedDashboard: (id: number, isShared: boolean) => ({ id, isShared }),
        /** The current state in which the dashboard is being viewed, see DashboardMode. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource | null) => ({ mode, source }),
        updateLayouts: (layouts: Layouts) => ({ layouts }),
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        saveLayouts: true,
        updateItemColor: (insightNumericId: number, color: string | null) => ({ insightNumericId, color }),
        removeItem: (insight: Partial<InsightModel>) => ({ insight }),
        refreshAllDashboardItems: (items?: InsightModel[]) => ({ items }),
        refreshAllDashboardItemsManual: true,
        resetInterval: true,
        updateAndRefreshDashboard: true,
        setDates: (dateFrom: string, dateTo: string | null, reloadDashboard = true) => ({
            dateFrom,
            dateTo,
            reloadDashboard,
        }),
        setProperties: (properties: AnyPropertyFilter[]) => ({ properties }),
        setAutoRefresh: (enabled: boolean, interval: number) => ({ enabled, interval }),
        setRefreshStatus: (shortId: InsightShortId, loading = false) => ({ shortId, loading }),
        setRefreshStatuses: (shortIds: InsightShortId[], loading = false) => ({ shortIds, loading }),
        setRefreshError: (shortId: InsightShortId) => ({ shortId }),
        reportDashboardViewed: true, // Reports `viewed dashboard` and `dashboard analyzed` events
        setShouldReportOnAPILoad: (shouldReport: boolean) => ({ shouldReport }), // See reducer for details
    },

    loaders: ({ actions, props }) => ({
        // TODO this is a terrible name... it is "dashboard" but there's a "dashboard" reducer ¯\_(ツ)_/¯
        allItems: [
            null as DashboardType | null,
            {
                loadDashboardItems: async ({ refresh }) => {
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
                              })}`
                        const dashboard = await api.get(apiUrl)
                        actions.setDates(dashboard.filters.date_from, dashboard.filters.date_to, false)
                        return dashboard
                    } catch (error: any) {
                        actions.setReceivedErrorsFromAPI(true)
                        if (error.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        receivedErrorsFromAPI: [
            false,
            {
                setReceivedErrorsFromAPI: (
                    _: boolean,
                    {
                        receivedErrors,
                    }: {
                        receivedErrors: boolean
                    }
                ) => receivedErrors,
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
                setProperties: (state, { properties }) => ({
                    ...state,
                    properties: properties || null,
                }),
            },
        ],
        allItems: [
            null as DashboardType | null,
            {
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
                [dashboardsModel.actionTypes.updateDashboardItem]: (state, { item, dashboardIds }) => {
                    if (dashboardIds && props.id && !dashboardIds.includes(props.id)) {
                        // this update is not for this dashboard
                        return state
                    }

                    if (state) {
                        const itemIndex = state.items.findIndex((i) => i.short_id === item.short_id)
                        const newItems = state.items.slice(0)
                        if (itemIndex >= 0) {
                            newItems[itemIndex] = mergeWithDashboardTile(item, newItems[itemIndex])
                        } else {
                            newItems.push(item)
                        }
                        return {
                            ...state,
                            items: newItems
                                .filter((i) => !i.deleted)
                                .filter((i) => (i.dashboards || []).includes(props.id || -1)),
                        } as DashboardType
                    }
                    return null
                },
                [dashboardsModel.actionTypes.updateDashboardSuccess]: (state, { dashboard }) => {
                    return state && dashboard && state.id === dashboard.id ? dashboard : state
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
                updateItemColor: (state, { insightNumericId, color }) => {
                    return {
                        ...state,
                        items: state?.items.map((i) => (i.id === insightNumericId ? { ...i, color } : i)),
                    } as DashboardType
                },
                removeItem: (state, { insight }) => {
                    return {
                        ...state,
                        items: state?.items.filter((i) => i.id !== insight.id),
                    } as DashboardType
                },
                [insightsModel.actionTypes.duplicateInsightSuccess]: (state, { item }): DashboardType => {
                    return {
                        ...state,
                        items:
                            props.id && item.dashboards?.includes(parseInt(props.id.toString()))
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
            { persist: true, prefix: '1_' },
            {
                setAutoRefresh: (_, { enabled, interval }) => ({ enabled, interval }),
            },
        ],
        shouldReportOnAPILoad: [
            /* Whether to report viewed/analyzed events after the API is loaded (and this logic is mounted).
            We need this because the DashboardView component might be mounted (and subsequent `useEffect`) before the API request
            to `loadDashboardItems` is completed (e.g. if you open PH directly to a dashboard)
            */
            false,
            {
                setShouldReportOnAPILoad: (_, { shouldReport }) => shouldReport,
            },
        ],
    }),
    selectors: () => ({
        placement: [() => [(_, props) => props.placement], (placement) => placement],
        items: [(s) => [s.allItems], (allItems) => allItems?.items?.filter((i) => !i.deleted)],
        itemsLoading: [
            (s) => [s.allItemsLoading, s.refreshStatus],
            (allItemsLoading, refreshStatus) => {
                return allItemsLoading || Object.values(refreshStatus).some((s) => s.loading)
            },
        ],
        isRefreshing: [(s) => [s.refreshStatus], (refreshStatus) => (id: string) => !!refreshStatus[id]?.loading],
        highlightedInsightId: [
            () => [router.selectors.searchParams],
            (searchParams) => searchParams.highlightInsightId,
        ],
        lastRefreshed: [
            (s) => [s.items],
            (items) => {
                if (!items || !items.length) {
                    return null
                }
                let oldestLastRefreshed = null
                for (const item of items) {
                    const itemLastRefreshed = item.last_refresh ? dayjs(item.last_refresh) : null
                    if (
                        !oldestLastRefreshed ||
                        (itemLastRefreshed && itemLastRefreshed.isBefore(oldestLastRefreshed))
                    ) {
                        oldestLastRefreshed = itemLastRefreshed
                    }
                }
                return oldestLastRefreshed
            },
        ],
        dashboard: [
            () => [
                dashboardsModel.selectors.sharedDashboard,
                dashboardsModel.selectors.nameSortedDashboards,
                (_, { shareToken }) => shareToken,
                (_, { id }) => id,
            ],
            (sharedDashboard, dashboards, shareToken, id): DashboardType | null => {
                return shareToken ? sharedDashboard : dashboards.find((d) => d.id === id) || null
            },
        ],
        canEditDashboard: [
            (s) => [s.dashboard],
            (dashboard) => !!dashboard && dashboard.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit,
        ],
        canRestrictDashboard: [
            // Sync conditions with backend can_user_restrict
            (s) => [s.dashboard, userLogic.selectors.user, teamLogic.selectors.currentTeam],
            (dashboard, user, currentTeam): boolean =>
                !!dashboard &&
                !!user &&
                (user.uuid === dashboard.created_by?.uuid ||
                    (!!currentTeam?.effective_membership_level &&
                        currentTeam.effective_membership_level >= OrganizationMembershipLevel.Admin)),
        ],
        sizeKey: [
            (s) => [s.columns],
            (columns): DashboardLayoutSize | undefined => {
                const [size] = (Object.entries(BREAKPOINT_COLUMN_COUNTS).find(([, value]) => value === columns) ||
                    []) as [DashboardLayoutSize, number]
                return size
            },
        ],
        layouts: [
            (s) => [s.items],
            (items) => {
                // The dashboard redesign includes constraints on the size of dashboard items
                const minW = MIN_ITEM_WIDTH_UNITS
                const minH = MIN_ITEM_HEIGHT_UNITS

                const allLayouts: Partial<Record<keyof typeof BREAKPOINT_COLUMN_COUNTS, Layout[]>> = {}

                for (const col of Object.keys(BREAKPOINT_COLUMN_COUNTS) as (keyof typeof BREAKPOINT_COLUMN_COUNTS)[]) {
                    const layouts = items
                        ?.filter((i) => !i.deleted)
                        .map((item) => {
                            const isRetention =
                                item.filters.insight === InsightType.RETENTION &&
                                item.filters.display === ChartDisplayType.ActionsLineGraph
                            const defaultWidth =
                                isRetention || item.filters.display === ChartDisplayType.PathsViz ? 8 : 6
                            const defaultHeight = isRetention
                                ? 8
                                : item.filters.display === ChartDisplayType.PathsViz
                                ? 12.5
                                : 5
                            const layout = item.layouts && item.layouts[col]
                            const { x, y, w, h } = layout || {}
                            const width = Math.min(w || defaultWidth, BREAKPOINT_COLUMN_COUNTS[col])
                            return {
                                i: item.short_id,
                                x: Number.isInteger(x) && x + width - 1 < BREAKPOINT_COLUMN_COUNTS[col] ? x : 0,
                                y: Number.isInteger(y) ? y : Infinity,
                                w: width,
                                h: h || defaultHeight,
                                minW,
                                minH,
                            }
                        })

                    const cleanLayouts = layouts?.filter(({ y }) => y !== Infinity)

                    // array of -1 for each column
                    const lowestPoints = Array.from(Array(BREAKPOINT_COLUMN_COUNTS[col])).map(() => -1)

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
                            const segmentCount = BREAKPOINT_COLUMN_COUNTS[col] - w + 1
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
                                minW,
                                minH,
                            })

                            for (let k = lowestIndex; k <= lowestIndex + w - 1; k++) {
                                lowestPoints[k] = Math.max(lowestPoints[k], lowestDepth + h)
                            }
                        })

                    allLayouts[col] = cleanLayouts
                }
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
                    refresh: props.placement === DashboardPlacement.InternalMetrics,
                })
            }

            if (props.shareToken) {
                dashboardsModel.actions.loadSharedDashboard(props.shareToken)
            }
        },
        beforeUnmount: () => {
            if (cache.autoRefreshInterval) {
                window.clearInterval(cache.autoRefreshInterval)
                cache.autoRefreshInterval = null
            }
        },
    }),
    listeners: ({ actions, values, cache, props }) => ({
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
            if (!isUserLoggedIn()) {
                // If user is anonymous (i.e. viewing a shared dashboard logged out), we don't save any layout changes.
                return
            }
            if (!props.id) {
                // what are we saving layouts against?!
                return
            }
            await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                tile_layouts:
                    values.items?.map((item) => {
                        const layouts: Record<string, Layout> = {}
                        Object.entries(item.layouts).forEach(([layoutKey, layout]) => {
                            const { i, ...rest } = layout
                            layouts[layoutKey] = rest
                        })
                        return { id: item.id, layouts }
                    }) || [],
            })
        },
        updateItemColor: async ({ insightNumericId, color }) => {
            if (!props.id) {
                // what are we saving colors against?!
                return
            }

            return api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                colors: [{ id: insightNumericId, color }],
            })
        },
        removeItem: async ({ insight }) => {
            return api.update(`api/projects/${values.currentTeamId}/insights/${insight.id}`, {
                dashboards: insight.dashboards?.filter((id) => id !== props.id) ?? [],
            } as Partial<InsightModel>)
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

                    if (!props.id) {
                        // what are we loading the insight card on?!
                        return
                    }

                    const refreshedDashboardItem = await api.get(
                        `api/projects/${values.currentTeamId}/insights/${dashboardItem.id}/?${toParams({
                            refresh: true,
                            from_dashboard: props.id, // needed to load insight in correct context
                        })}`
                    )
                    breakpoint()

                    // reload the cached results inside the insight's logic
                    if (dashboardItem.filters.insight) {
                        const itemResultLogic = insightLogic?.findMounted({
                            dashboardItemId: dashboardItem.short_id,
                            dashboardId: props.id,
                            cachedInsight: dashboardItem,
                        })
                        itemResultLogic?.actions.setInsight(
                            { ...dashboardItem, result: refreshedDashboardItem.result },
                            { fromPersistentApi: true }
                        )
                    }

                    dashboardsModel.actions.updateDashboardItem(refreshedDashboardItem, [props.id])
                    actions.setRefreshStatus(dashboardItem.short_id)
                } catch (e: any) {
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
            await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                filters: values.filters,
            })
            actions.refreshAllDashboardItems()
        },
        setDates: ({ dateFrom, dateTo, reloadDashboard }) => {
            if (reloadDashboard) {
                actions.updateAndRefreshDashboard()
            }
            eventUsageLogic.actions.reportDashboardDateRangeChanged(dateFrom, dateTo)
        },
        setProperties: () => {
            actions.updateAndRefreshDashboard()
            eventUsageLogic.actions.reportDashboardPropertiesChanged()
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
            }

            if (mode) {
                eventUsageLogic.actions.reportDashboardModeToggled(mode, source)
            }
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
            if (
                values.lastRefreshed &&
                values.lastRefreshed.isBefore(now().subtract(3, 'hours')) &&
                values.featureFlags[FEATURE_FLAGS.AUTO_REFRESH_DASHBOARDS]
            ) {
                actions.refreshAllDashboardItems()
            } else {
                const notYetLoadedItems = values.allItems?.items?.filter((i) => !i.result)
                if (notYetLoadedItems && notYetLoadedItems?.length > 0) {
                    actions.refreshAllDashboardItems(notYetLoadedItems)
                }
            }
            if (values.shouldReportOnAPILoad) {
                actions.setShouldReportOnAPILoad(false)
                actions.reportDashboardViewed()
            }
        },
        reportDashboardViewed: async (_, breakpoint) => {
            // Caching `allItems`, as the dashboard might have unmounted after the breakpoint,
            // and "values.allItems" will then fail
            const { allItems } = values
            if (allItems) {
                eventUsageLogic.actions.reportDashboardViewed(allItems, !!props.shareToken)
                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish
                if (
                    router.values.location.pathname === urls.dashboard(allItems.id) ||
                    router.values.location.pathname === urls.projectHomepage() ||
                    (props.shareToken && router.values.location.pathname === urls.sharedDashboard(props.shareToken))
                ) {
                    eventUsageLogic.actions.reportDashboardViewed(allItems, !!props.shareToken, 10)
                }
            } else {
                // allItems has not loaded yet, report after API request is completed
                actions.setShouldReportOnAPILoad(true)
            }
        },
    }),
})
