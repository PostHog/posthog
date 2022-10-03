import { isBreakpoint, kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { clearDOMTextSelection, isUserLoggedIn, toParams } from 'lib/utils'
import { insightsModel } from '~/models/insightsModel'
import { DashboardPrivilegeLevel, OrganizationMembershipLevel } from 'lib/constants'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    AnyPropertyFilter,
    Breadcrumb,
    ChartDisplayType,
    DashboardLayoutSize,
    DashboardMode,
    DashboardPlacement,
    DashboardTile,
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
import { userLogic } from 'scenes/userLogic'
import { dayjs, now } from 'lib/dayjs'
import { lemonToast } from 'lib/components/lemonToast'

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
    dashboard?: DashboardType
    placement?: DashboardPlacement
}

export interface RefreshStatus {
    loading?: boolean
    refreshed?: boolean
    error?: boolean
    timer?: Date | null
}

export const AUTO_REFRESH_INITIAL_INTERVAL_SECONDS = 300

export const dashboardLogic = kea<dashboardLogicType>({
    path: ['scenes', 'dashboard', 'dashboardLogic'],
    connect: () => ({
        values: [teamLogic, ['currentTeamId']],
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
        loadExportedDashboard: (dashboard: DashboardType | null) => ({ dashboard }),
        loadDashboardItems: ({
            refresh,
        }: {
            refresh?: boolean
        } = {}) => ({
            refresh,
        }),
        triggerDashboardUpdate: (payload) => ({ payload }),
        /** The current state in which the dashboard is being viewed, see DashboardMode. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource | null) => ({ mode, source }),
        updateLayouts: (layouts: Layouts) => ({ layouts }),
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        updateItemColor: (insightNumericId: number, color: string | null) => ({ insightNumericId, color }),
        removeItem: (insight: Partial<InsightModel>) => ({ insight }),
        refreshAllDashboardItems: (tiles?: DashboardTile[]) => ({ tiles }),
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
        setSubscriptionMode: (enabled: boolean, id?: number | 'new') => ({ enabled, id }),
    },

    loaders: ({ actions, props, values }) => ({
        // TODO this is a terrible name... it is "dashboard" but there's a "dashboard" reducer ¯\_(ツ)_/¯
        allItems: [
            null as DashboardType | null,
            {
                loadDashboardItems: async ({ refresh }) => {
                    if (!props.id) {
                        console.warn('Called `loadDashboardItems` but ID is not set.')
                        return
                    }

                    try {
                        const apiUrl = values.apiUrl(refresh)
                        const dashboard = await api.get(apiUrl)
                        actions.setDates(dashboard.filters.date_from, dashboard.filters.date_to, false)
                        return dashboard
                    } catch (error: any) {
                        if (error.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
                updateLayouts: async ({ layouts }) => {
                    if (!isUserLoggedIn()) {
                        // If user is anonymous (i.e. viewing a shared dashboard logged out), we don't save any layout changes.
                        return
                    }
                    if (!props.id) {
                        // what are we saving layouts against?!
                        return
                    }

                    const itemLayouts: Record<number, Partial<Record<string, Layout>>> = {}

                    Object.entries(layouts).forEach(([col, layout]) => {
                        layout.forEach((layoutItem) => {
                            const insightId = values.shortIdToId?.[layoutItem.i]
                            if (!insightId) {
                                // it _should_ be impossible for a layout item to not be in this mapping
                                throw new Error('Could not update layouts for unknown insight')
                            }

                            if (!itemLayouts[insightId]) {
                                itemLayouts[insightId] = {}
                            }
                            itemLayouts[insightId][col] = layoutItem
                        })
                    })

                    return await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                        tile_layouts: Object.entries(itemLayouts).map(([id, layouts]) => ({
                            id,
                            layouts,
                        })),
                    })
                },
                updateItemColor: async ({ insightNumericId, color }) => {
                    if (!props.id) {
                        // what are we saving colors against?!
                        return
                    }

                    return await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                        colors: [{ id: insightNumericId, color }],
                    })
                },
                removeItem: async ({ insight }) => {
                    try {
                        await api.update(`api/projects/${values.currentTeamId}/insights/${insight.id}`, {
                            dashboards: insight.dashboards?.filter((id) => id !== props.id) ?? [],
                        } as Partial<InsightModel>)

                        return {
                            ...values.allItems,
                            tiles: values.allItems?.tiles.filter((t) => t.insight.id !== insight.id),
                        } as DashboardType
                    } catch (e) {
                        lemonToast.error('Could not remove item: ' + e)
                        return values.allItems
                    }
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        receivedErrorsFromAPI: [
            false,
            {
                loadDashboardItemsSuccess: () => false,
                loadDashboardItemsFailure: () => true,
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
                loadExportedDashboard: (_, { dashboard }) => dashboard,
                [dashboardsModel.actionTypes.updateDashboardInsight]: (state, { insight, extraDashboardIds }) => {
                    const targetDashboards = (insight.dashboards || []).concat(extraDashboardIds || [])
                    if (!props.id) {
                        // what are we even updating?
                        return state
                    }
                    if (!targetDashboards.includes(props.id)) {
                        // this update is not for this dashboard
                        return state
                    }

                    if (state) {
                        const tileIndex = state.tiles.findIndex((t) => t.insight.short_id === insight.short_id)
                        const newTiles = state.tiles.slice(0)

                        if (tileIndex >= 0) {
                            if (insight.dashboards?.includes(props.id)) {
                                newTiles[tileIndex] = { ...newTiles[tileIndex], insight: insight }
                            } else {
                                newTiles.splice(tileIndex, 1)
                            }
                        } else {
                            newTiles.push({ insight: insight, layouts: {}, color: null } as DashboardTile)
                        }

                        return {
                            ...state,
                            tiles: newTiles.filter((t) => !t.insight.deleted),
                        } as DashboardType
                    }

                    return null
                },
                [dashboardsModel.actionTypes.updateDashboardTile]: (state, { tile, extraDashboardIds }) => {
                    const targetDashboards = (tile.insight.dashboards || []).concat(extraDashboardIds || [])
                    if (!props.id) {
                        // what are we even updating?
                        return state
                    }
                    if (!targetDashboards.includes(props.id)) {
                        // this update is not for this dashboard
                        return state
                    }

                    if (state) {
                        const tileIndex = state.tiles.findIndex((t) => t.insight.short_id === tile.insight.short_id)
                        const newTiles = state.tiles.slice(0)

                        if (tileIndex >= 0) {
                            if (tile.insight.dashboards?.includes(props.id)) {
                                newTiles[tileIndex] = { ...newTiles[tileIndex], ...tile }
                            } else {
                                newTiles.splice(tileIndex, 1)
                            }
                        } else {
                            newTiles.push(tile)
                        }

                        return {
                            ...state,
                            tiles: newTiles.filter((t) => !t.insight.deleted),
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
                        items: state?.tiles.map((t) =>
                            t.insight.short_id === shortId
                                ? {
                                      ...t,
                                      ...(refreshing != null ? { refreshing } : {}),
                                      ...(last_refresh != null ? { last_refresh } : {}),
                                  }
                                : t
                        ),
                    } as DashboardType
                },
                [insightsModel.actionTypes.duplicateInsightSuccess]: (state, { item }): DashboardType => {
                    return {
                        ...state,
                        tiles:
                            props.id && item.dashboards?.includes(parseInt(props.id.toString()))
                                ? [
                                      ...(state?.tiles || []),
                                      { insight: item, layouts: {}, color: null } as DashboardTile,
                                  ]
                                : state?.tiles,
                    } as DashboardType
                },
                // TODO this is broken in production cos the logic didn't already listen for it
                [insightsModel.actionTypes.renameInsightSuccess]: (state, { item }) => {
                    const matchingTile = state?.tiles.findIndex((t) => t.insight.short_id === item.short_id)
                    const tiles = state?.tiles.slice(0)
                    if (!matchingTile || matchingTile === -1 || !tiles) {
                        return state
                    }

                    tiles[matchingTile] = { ...tiles[matchingTile], insight: item }
                    return {
                        ...state,
                        tiles: tiles,
                    } as DashboardType
                },
            },
        ],
        loadTimer: [null as Date | null, { loadDashboardItems: () => new Date() }],
        refreshStatus: [
            {} as Record<string, RefreshStatus>,
            {
                setRefreshStatus: (state, { shortId, loading }) => ({
                    ...state,
                    [shortId]: loading
                        ? { loading: true, timer: new Date() }
                        : { refreshed: true, timer: state[shortId]?.timer || null },
                }),
                setRefreshStatuses: (state, { shortIds, loading }) =>
                    Object.fromEntries(
                        shortIds.map((shortId) => [
                            shortId,
                            loading
                                ? { loading: true, timer: new Date() }
                                : { refreshed: true, timer: state[shortId]?.timer || null },
                        ])
                    ) as Record<string, RefreshStatus>,
                setRefreshError: (state, { shortId }) => ({
                    ...state,
                    [shortId]: { error: true, timer: state[shortId]?.timer || null },
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

        showSubscriptions: [
            false,
            {
                setSubscriptionMode: (_, { enabled }) => enabled,
            },
        ],
        subscriptionId: [
            null as number | 'new' | null,
            {
                setSubscriptionMode: (_, { id }) => id || null,
            },
        ],
    }),
    selectors: () => ({
        placement: [() => [(_, props) => props.placement], (placement) => placement ?? DashboardPlacement.Dashboard],
        apiUrl: [
            () => [(_, props) => props.id],
            (id) => {
                return (refresh?: boolean) =>
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}/?${toParams({
                        refresh,
                    })}`
            },
        ],
        items: [
            (s) => [s.allItems],
            (allItems) => allItems?.tiles?.filter((i) => !i.insight.deleted).map((i) => i.insight),
        ],
        tiles: [(s) => [s.allItems], (allItems) => allItems?.tiles || []],
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
            () => [dashboardsModel.selectors.nameSortedDashboards, (_, { id }) => id],
            (dashboards, id): DashboardType | null => {
                return dashboards.find((d) => d.id === id) || null
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
            (s) => [s.tiles],
            (tiles) => {
                // The dashboard redesign includes constraints on the size of dashboard items
                const minW = MIN_ITEM_WIDTH_UNITS
                const minH = MIN_ITEM_HEIGHT_UNITS

                const allLayouts: Partial<Record<keyof typeof BREAKPOINT_COLUMN_COUNTS, Layout[]>> = {}

                for (const col of Object.keys(BREAKPOINT_COLUMN_COUNTS) as (keyof typeof BREAKPOINT_COLUMN_COUNTS)[]) {
                    const layouts = tiles.map((tile) => {
                        const isRetention =
                            tile.insight.filters.insight === InsightType.RETENTION &&
                            tile.insight.filters.display === ChartDisplayType.ActionsLineGraph
                        const defaultWidth =
                            isRetention || tile.insight.filters.display === ChartDisplayType.PathsViz ? 8 : 6
                        const defaultHeight = isRetention
                            ? 8
                            : tile.insight.filters.display === ChartDisplayType.PathsViz
                            ? 12.5
                            : 5
                        const layout = tile.layouts && tile.layouts[col]
                        const { x, y, w, h } = layout || {}
                        const width = Math.min(w || defaultWidth, BREAKPOINT_COLUMN_COUNTS[col])
                        return {
                            i: tile.insight.short_id,
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
        shortIdToId: [
            (s) => [s.items],
            (items): Record<InsightShortId, number> => {
                return (items ?? []).reduce((acc, curr) => {
                    acc[curr.short_id] = Number(curr.id)
                    return acc
                }, {})
            },
        ],
    }),
    events: ({ actions, cache, props }) => ({
        afterMount: () => {
            if (props.id) {
                if (props.dashboard) {
                    actions.loadExportedDashboard(props.dashboard)
                } else {
                    actions.loadDashboardItems({
                        refresh: props.placement === DashboardPlacement.InternalMetrics,
                    })
                }
            }
        },
        beforeUnmount: () => {
            if (cache.autoRefreshInterval) {
                window.clearInterval(cache.autoRefreshInterval)
                cache.autoRefreshInterval = null
            }
        },
    }),
    sharedListeners: ({ values, props }) => ({
        reportRefreshTiming: ({ shortId }) => {
            const refreshStatus = values.refreshStatus[shortId]

            if (refreshStatus?.timer) {
                const loadingMilliseconds = new Date().getTime() - refreshStatus.timer.getTime()
                eventUsageLogic.actions.reportInsightRefreshTime(loadingMilliseconds, shortId)
            }
        },
        reportLoadTiming: () => {
            if (!props.id) {
                // what even is loading?!
                return
            }
            if (values.loadTimer) {
                const loadingMilliseconds = new Date().getTime() - values.loadTimer.getTime()
                eventUsageLogic.actions.reportDashboardLoadingTime(loadingMilliseconds, props.id)
            }
        },
    }),
    listeners: ({ actions, values, cache, props, sharedListeners }) => ({
        setRefreshError: sharedListeners.reportRefreshTiming,
        setRefreshStatuses: sharedListeners.reportRefreshTiming,
        setRefreshStatus: sharedListeners.reportRefreshTiming,
        loadDashboardItemsFailure: sharedListeners.reportLoadTiming,
        triggerDashboardUpdate: ({ payload }) => {
            if (values.dashboard) {
                dashboardsModel.actions.updateDashboard({ id: values.dashboard.id, ...payload })
            }
        },
        refreshAllDashboardItemsManual: () => {
            // reset auto refresh interval
            actions.resetInterval()
            actions.refreshAllDashboardItems()
        },
        refreshAllDashboardItems: async ({ tiles }, breakpoint) => {
            if (!props.id) {
                // what are we loading the insight card on?!
                return
            }
            const dashboardId: number = props.id

            const insights = tiles?.map((t) => t.insight) || values.items || []

            // Don't do anything if there's nothing to refresh
            if (insights.length === 0) {
                return
            }

            let breakpointTriggered = false
            actions.setRefreshStatuses(
                insights.map((item) => item.short_id),
                true
            )

            // array of functions that reload each item
            const fetchItemFunctions = insights.map((insight) => async () => {
                try {
                    breakpoint()

                    const refreshedInsight = await api.get(
                        `api/projects/${values.currentTeamId}/insights/${insight.id}/?${toParams({
                            refresh: true,
                            from_dashboard: dashboardId, // needed to load insight in correct context
                        })}`
                    )
                    breakpoint()

                    // reload the cached results inside the insight's logic
                    if (insight.filters.insight) {
                        const itemResultLogic = insightLogic?.findMounted({
                            dashboardItemId: insight.short_id,
                            dashboardId: dashboardId,
                            cachedInsight: insight,
                        })
                        itemResultLogic?.actions.setInsight(
                            { ...insight, result: refreshedInsight.result },
                            { fromPersistentApi: true }
                        )
                    }

                    dashboardsModel.actions.updateDashboardInsight(refreshedInsight)
                    actions.setRefreshStatus(insight.short_id)
                } catch (e: any) {
                    if (isBreakpoint(e)) {
                        breakpointTriggered = true
                    } else {
                        actions.setRefreshError(insight.short_id)
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

            eventUsageLogic.actions.reportDashboardRefreshed(dashboardId, values.lastRefreshed)
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
        loadDashboardItemsSuccess: function (...args) {
            sharedListeners.reportLoadTiming(...args)

            // Initial load of actual data for dashboard items after general dashboard is fetched
            if (values.lastRefreshed && values.lastRefreshed.isBefore(now().subtract(3, 'hours'))) {
                actions.refreshAllDashboardItems()
            } else {
                const notYetLoadedItems = values.allItems?.tiles?.filter((i) => !i.insight.result)
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
            const { allItems, lastRefreshed } = values
            if (allItems) {
                eventUsageLogic.actions.reportDashboardViewed(allItems, lastRefreshed)
                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish
                if (
                    router.values.location.pathname === urls.dashboard(allItems.id) ||
                    router.values.location.pathname === urls.projectHomepage() ||
                    router.values.location.pathname.startsWith(urls.sharedDashboard(''))
                ) {
                    eventUsageLogic.actions.reportDashboardViewed(allItems, lastRefreshed, 10)
                }
            } else {
                // allItems has not loaded yet, report after API request is completed
                actions.setShouldReportOnAPILoad(true)
            }
        },
    }),

    urlToAction: ({ actions }) => ({
        '/dashboard/:id/subscriptions(/:subscriptionId)': ({ subscriptionId }) => {
            const id = subscriptionId
                ? subscriptionId == 'new'
                    ? subscriptionId
                    : parseInt(subscriptionId, 10)
                : undefined
            actions.setSubscriptionMode(true, id)
            actions.setDashboardMode(null, null)
        },

        '/dashboard/:id': () => {
            actions.setSubscriptionMode(false, undefined)
            actions.setDashboardMode(null, DashboardEventSource.Browser)
        },
        '/dashboard/:id/sharing': () => {
            actions.setSubscriptionMode(false, undefined)
            actions.setDashboardMode(DashboardMode.Sharing, null)
        },
    }),
})
