import { kea } from 'kea'
import { prompt } from 'lib/logic/prompt'
import { errorToast, objectsEqual, toParams, uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from './insightLogicType'
import {
    AvailableFeature,
    Breadcrumb,
    DashboardItemType,
    FilterType,
    InsightLogicProps,
    InsightShortId,
    InsightType,
    ItemMode,
    SetInsightOptions,
} from '~/types'
import { captureInternalMetric } from 'lib/internalMetrics'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import React from 'react'
import { Link } from 'lib/components/Link'
import { filterTrendsClientSideParams, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { dashboardsModel } from '~/models/dashboardsModel'
import { pollFunnel } from 'scenes/funnels/funnelUtils'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { extractObjectDiffKeys, findInsightFromMountedLogic, getInsightId } from './utils'
import { teamLogic } from '../teamLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'
import { generateRandomAnimal } from 'lib/utils/randomAnimal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

/*
InsightLogic maintains state for changing between insight features
This includes handling the urls and view state
*/

const SHOW_TIMEOUT_MESSAGE_AFTER = 15000

export const defaultFilterTestAccounts = (): boolean => {
    return localStorage.getItem('default_filter_test_accounts') === 'true' || false
}

export const insightLogic = kea<insightLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['scenes', 'insights', 'insightLogic', key],

    connect: {
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
        logic: [eventUsageLogic, dashboardsModel],
    },

    actions: () => ({
        setActiveView: (type: InsightType) => ({ type }),
        updateActiveView: (type: InsightType) => ({ type }),
        setFilters: (filters: Partial<FilterType>, insightMode?: ItemMode) => ({ filters, insightMode }),
        reportInsightViewed: (filters: Partial<FilterType>, previousFilters?: Partial<FilterType>) => ({
            filters,
            previousFilters,
        }),
        startQuery: (queryId: string) => ({ queryId }),
        endQuery: (
            queryId: string,
            view: InsightType,
            lastRefresh: string | null,
            exception?: Record<string, any>
        ) => ({
            queryId,
            view,
            lastRefresh,
            exception,
        }),
        abortQuery: (queryId: string, view: InsightType, scene: Scene | null, exception?: Record<string, any>) => ({
            queryId,
            view,
            scene,
            exception,
        }),
        setShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setShowErrorMessage: (showErrorMessage: boolean) => ({ showErrorMessage }),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setTimeout: (timeout: number | null) => ({ timeout }),
        setLastRefresh: (lastRefresh: string | null) => ({ lastRefresh }),
        setNotFirstLoad: () => {},
        saveNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        setInsight: (insight: Partial<DashboardItemType>, options: SetInsightOptions) => ({
            insight,
            options,
        }),
        saveAs: true,
        saveAsNamingSuccess: (name: string) => ({ name }),
        setInsightMode: (mode: ItemMode, source: InsightEventSource | null) => ({ mode, source }),
        setInsightDescription: (description: string) => ({ description }),
        saveInsight: (options?: Record<string, any>) => ({ setViewMode: options?.setViewMode }),
        setTagLoading: (tagLoading: boolean) => ({ tagLoading }),
        fetchedResults: (filters: Partial<FilterType>) => ({ filters }),
        loadInsight: (shortId: InsightShortId, { doNotLoadResults }: { doNotLoadResults?: boolean } = {}) => ({
            shortId,
            doNotLoadResults,
        }),
        updateInsight: (
            insight: Partial<DashboardItemType>,
            callback?: (insight: Partial<DashboardItemType>) => void
        ) => ({ insight, callback }),
        loadResults: (refresh = false) => ({ refresh, queryId: uuid() }),
        setInsightMetadata: (metadata: Partial<DashboardItemType>) => ({ metadata }),
        createAndRedirectToNewInsight: (filters?: Partial<FilterType>) => ({ filters }),
    }),
    loaders: ({ actions, cache, values, props }) => ({
        insight: [
            {
                short_id: props.dashboardItemId,
                tags: [],
                filters: props.cachedResults ? props.filters || {} : {},
                result: props.cachedResults || null,
            } as Partial<DashboardItemType>,
            {
                loadInsight: async ({ shortId }) => {
                    return (
                        await api.get(
                            `api/projects/${teamLogic.values.currentTeamId}/insights/?short_id=${encodeURIComponent(
                                shortId
                            )}`
                        )
                    ).results[0]
                },
                updateInsight: async ({ insight, callback }, breakpoint) => {
                    if (!Object.entries(insight).length) {
                        return values.insight
                    }
                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                        insight
                    )
                    breakpoint()
                    const updatedInsight: Partial<DashboardItemType> = {
                        ...response,
                        result: response.result || values.insight.result,
                    }
                    callback?.(updatedInsight)
                    savedInsightsLogic.findMounted()?.actions.loadInsights()
                    dashboardsModel.actions.updateDashboardItem(updatedInsight)
                    return updatedInsight
                },
                setInsightMetadata: async ({ metadata }, breakpoint) => {
                    if (values.insightMode === ItemMode.Edit) {
                        return { ...values.insight, ...metadata }
                    }

                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                        metadata
                    )
                    breakpoint()

                    // only update the fields that we changed
                    const updatedInsight: Partial<DashboardItemType> = { ...values.insight }
                    for (const key of Object.keys(metadata)) {
                        updatedInsight[key] = response[key]
                    }
                    savedInsightsLogic.findMounted()?.actions.loadInsights()
                    dashboardsModel.actions.updateDashboardItem(updatedInsight)
                    return updatedInsight
                },
                // using values.filters, query for new insight results
                loadResults: async ({ refresh, queryId }, breakpoint) => {
                    // fetch this now, as it might be different when we report below
                    const scene = sceneLogic.isMounted() ? sceneLogic.values.scene : null

                    // If a query is in progress, debounce before making the second query
                    if (cache.abortController) {
                        await breakpoint(300)
                        cache.abortController.abort()
                    }
                    cache.abortController = new AbortController()

                    const { filters } = values
                    const insight = (filters.insight as InsightType | undefined) || InsightType.TRENDS
                    const params = { ...filters, ...(refresh ? { refresh: true } : {}) }

                    const dashboardItemId = props.dashboardItemId
                    actions.startQuery(queryId)
                    if (dashboardItemId && dashboardsModel.isMounted()) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                    }

                    let response
                    const { currentTeamId } = values
                    if (!currentTeamId) {
                        throw new Error("Can't load insight before current project is determined.")
                    }
                    try {
                        if (
                            insight === InsightType.TRENDS ||
                            insight === InsightType.STICKINESS ||
                            insight === InsightType.LIFECYCLE
                        ) {
                            response = await api.get(
                                `api/projects/${currentTeamId}/insights/trend/?${toParams(
                                    filterTrendsClientSideParams(params)
                                )}`,
                                cache.abortController.signal
                            )
                        } else if (insight === InsightType.SESSIONS || filters?.session) {
                            response = await api.get(
                                `api/projects/${currentTeamId}/insights/session/?${toParams(
                                    filterTrendsClientSideParams(params)
                                )}`,
                                cache.abortController.signal
                            )
                        } else if (insight === InsightType.RETENTION) {
                            response = await api.get(
                                `api/projects/${currentTeamId}/insights/retention/?${toParams(params)}`,
                                cache.abortController.signal
                            )
                        } else if (insight === InsightType.FUNNELS) {
                            response = await pollFunnel(currentTeamId, params)
                        } else if (insight === InsightType.PATHS) {
                            response = await api.create(`api/projects/${currentTeamId}/insights/path`, params)
                        } else {
                            throw new Error(`Can not load insight of type ${insight}`)
                        }
                    } catch (e) {
                        if (e.name === 'AbortError') {
                            actions.abortQuery(queryId, insight, scene, e)
                        }
                        breakpoint()
                        cache.abortController = null
                        actions.endQuery(queryId, insight, null, e)
                        if (dashboardItemId && dashboardsModel.isMounted()) {
                            dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                        }
                        if (filters.insight === InsightType.FUNNELS) {
                            eventUsageLogic.actions.reportFunnelCalculated(
                                filters.events?.length || 0,
                                filters.actions?.length || 0,
                                filters.interval || '',
                                filters.funnel_viz_type,
                                false,
                                e.message
                            )
                        }
                        throw e
                    }
                    breakpoint()
                    cache.abortController = null
                    actions.endQuery(
                        queryId,
                        (values.filters.insight as InsightType) || InsightType.TRENDS,
                        response.last_refresh
                    )
                    if (dashboardItemId && dashboardsModel.isMounted()) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(
                            dashboardItemId,
                            false,
                            response.last_refresh
                        )
                    }
                    if (filters.insight === InsightType.FUNNELS) {
                        eventUsageLogic.actions.reportFunnelCalculated(
                            filters.events?.length || 0,
                            filters.actions?.length || 0,
                            filters.interval || '',
                            filters.funnel_viz_type,
                            true
                        )
                    }

                    return {
                        ...values.insight,
                        result: response.result,
                        next: response.next,
                        filters,
                    } as Partial<DashboardItemType>
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        insight: {
            loadInsight: (state, { shortId }) =>
                shortId === state.short_id
                    ? state
                    : {
                          // blank slate if switched to a new insight
                          short_id: shortId,
                          tags: [],
                          result: null,
                          filters: {},
                      },
            setInsight: (state, { insight, options: { shouldMergeWithExisting } }) => ({
                ...(shouldMergeWithExisting ? state : {}),
                ...insight,
            }),
            setInsightMetadata: (state, { metadata }) => ({ ...state, ...metadata }),
        },
        /* filters contains the in-flight filters, might not (yet?) be the same as insight.filters */
        filters: [
            () => props.filters || ({} as Partial<FilterType>),
            {
                setFilters: (state, { filters }) => cleanFilters(filters, state),
                setInsight: (state, { insight: { filters }, options: { overrideFilter } }) =>
                    overrideFilter ? cleanFilters(filters || {}) : state,
                loadInsightSuccess: (state, { insight }) =>
                    Object.keys(state).length === 0 && insight.filters ? insight.filters : state,
                loadResultsSuccess: (state, { insight }) =>
                    Object.keys(state).length === 0 && insight.filters ? insight.filters : state,
            },
        ],
        /* savedFilters contain filters that are persisted on an insight */
        savedFilters: [
            () => props.filters || ({} as Partial<FilterType>),
            {
                setInsight: (state, { insight: { filters }, options: { fromPersistentApi } }) =>
                    fromPersistentApi ? cleanFilters(filters || {}) : state,
                loadInsightSuccess: (_, { insight }) => cleanFilters(insight.filters || {}),
                updateInsightSuccess: (_, { insight }) => cleanFilters(insight.filters || {}),
            },
        ],
        showTimeoutMessage: [false, { setShowTimeoutMessage: (_, { showTimeoutMessage }) => showTimeoutMessage }],
        maybeShowTimeoutMessage: [
            false,
            {
                // Only show timeout message if timer is still running
                setShowTimeoutMessage: (_, { showTimeoutMessage }) => showTimeoutMessage,
                endQuery: (_, { exception }) => !!exception && exception.status !== 500,
                startQuery: () => false,
                setActiveView: () => false,
            },
        ],
        showErrorMessage: [false, { setShowErrorMessage: (_, { showErrorMessage }) => showErrorMessage }],
        maybeShowErrorMessage: [
            false,
            {
                endQuery: (_, { exception }) => exception?.status >= 400,
                startQuery: () => false,
                setActiveView: () => false,
            },
        ],
        timeout: [null as number | null, { setTimeout: (_, { timeout }) => timeout }],
        lastRefresh: [
            null as string | null,
            {
                setLastRefresh: (_, { lastRefresh }) => lastRefresh,
                setActiveView: () => null,
            },
        ],
        isLoading: [
            false,
            {
                setIsLoading: (_, { isLoading }) => isLoading,
                loadInsightSuccess: () => false,
                loadInsightFailure: () => false,
                loadInsight: () => true,
            },
        ],
        /*
        isFirstLoad determines if this is the first graph being shown after the component is mounted (used for analytics)
        */
        isFirstLoad: [
            true,
            {
                setNotFirstLoad: () => false,
            },
        ],
        queryStartTimes: [
            {} as Record<string, number>,
            {
                startQuery: (state, { queryId }) => ({ ...state, [queryId]: new Date().getTime() }),
            },
        ],
        lastInsightModeSource: [
            null as InsightEventSource | null,
            {
                setInsightMode: (_, { source }) => source,
            },
        ],
        insightMode: [
            ItemMode.View as ItemMode,
            {
                setInsightMode: (_, { mode }) => mode,
                setFilters: (state, { insightMode }) => (typeof insightMode !== 'undefined' ? insightMode : state),
            },
        ],
        tagLoading: [
            false,
            {
                setTagLoading: (_, { tagLoading }) => tagLoading,
            },
        ],
    }),
    selectors: {
        /** filters for data that's being displayed, might not be same as savedFilters or filters */
        loadedFilters: [(s) => [s.insight], (insight) => insight.filters],
        insightProps: [() => [(_, props) => props], (props): InsightLogicProps => props],
        insightName: [(s) => [s.insight], (insight) => insight.name],
        activeView: [(s) => [s.filters], (filters) => filters.insight || InsightType.TRENDS],
        loadedView: [
            (s) => [s.insight, s.activeView],
            ({ filters }, activeView) => filters?.insight || activeView || InsightType.TRENDS,
        ],
        clickhouseFeaturesEnabled: [
            () => [preflightLogic.selectors.preflight],
            (preflight) => !!preflight?.is_clickhouse_enabled,
        ],
        filtersChanged: [
            (s) => [s.savedFilters, s.filters],
            (savedFilters, filters) =>
                filters && savedFilters && !objectsEqual(cleanFilters(savedFilters), cleanFilters(filters)),
        ],
        metadataEditable: [
            () => [userLogic.selectors.user],
            (user) => user?.organization?.available_features?.includes(AvailableFeature.DASHBOARD_COLLABORATION),
        ],
        syncWithUrl: [
            () => [(_, props: InsightLogicProps) => props.syncWithUrl, router.selectors.location],
            (syncWithUrl, { pathname }) => syncWithUrl && pathname.startsWith('/insights/'),
        ],
        breadcrumbs: [
            (s) => [s.insight],
            (insight): Breadcrumb[] => [
                {
                    name: 'Insights',
                    path: urls.savedInsights(),
                },
                {
                    name: insight?.id ? insight.name || 'Unnamed' : null,
                },
            ],
        ],
        isViewedOnDashboard: [() => [router.selectors.location], ({ pathname }) => pathname.startsWith('/dashboard/')],
        createInsightUrl: [
            (s) => [s.insight, s.filters],
            ({ short_id, filters }) =>
                (insightType: InsightType) =>
                    short_id
                        ? urls.insightEdit(short_id, cleanFilters({ ...filters, insight: insightType }, filters))
                        : undefined,
        ],
    },
    listeners: ({ actions, selectors, values, props }) => ({
        setFilters: async ({ filters }, _, __, previousState) => {
            const previousFilters = selectors.filters(previousState)
            if (objectsEqual(previousFilters, filters)) {
                return
            }

            actions.reportInsightViewed(filters, previousFilters)
            actions.setNotFirstLoad()

            const filterLength = (filter?: Partial<FilterType>): number =>
                (filter?.events?.length || 0) + (filter?.actions?.length || 0)

            const insightChanged = values.loadedFilters?.insight && filters.insight !== values.loadedFilters?.insight

            const backendFilterChanged = !objectsEqual(
                Object.assign({}, values.filters, {
                    layout: undefined,
                    hiddenLegendKeys: undefined,
                    funnel_advanced: undefined,
                }),
                Object.assign({}, values.loadedFilters, {
                    layout: undefined,
                    hiddenLegendKeys: undefined,
                    funnel_advanced: undefined,
                })
            )

            // Auto-reload when setting filters
            if (
                backendFilterChanged &&
                (values.filters.insight !== InsightType.FUNNELS ||
                    // Auto-reload on funnels if with clickhouse
                    values.clickhouseFeaturesEnabled ||
                    // Or if tabbing to the funnels insight
                    insightChanged ||
                    // If user started from empty state (<2 steps) and added a new step
                    (filterLength(values.loadedFilters) === 1 && filterLength(values.filters) === 2))
            ) {
                actions.loadResults()
            }
        },
        reportInsightViewed: async ({ filters, previousFilters }, breakpoint) => {
            const { fromDashboard } = router.values.hashParams
            const changedKeysObj: Record<string, any> | undefined =
                previousFilters && extractObjectDiffKeys(previousFilters, filters)

            eventUsageLogic.actions.reportInsightViewed(
                filters || {},
                values.insightMode,
                values.isFirstLoad,
                Boolean(fromDashboard),
                0,
                changedKeysObj
            )
            await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish

            eventUsageLogic.actions.reportInsightViewed(
                filters || {},
                values.insightMode,
                values.isFirstLoad,
                Boolean(fromDashboard),
                10,
                changedKeysObj
            )
        },
        startQuery: () => {
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            values.timeout && clearTimeout(values.timeout || undefined)
            const view = values.activeView
            actions.setTimeout(
                window.setTimeout(() => {
                    if (values && view == values.activeView) {
                        actions.setShowTimeoutMessage(true)
                        const tags = {
                            insight: values.activeView,
                            scene: sceneLogic.isMounted() ? sceneLogic.values.scene : null,
                        }
                        posthog.capture('insight timeout message shown', tags)
                        captureInternalMetric({ method: 'incr', metric: 'insight_timeout', value: 1, tags })
                    }
                }, SHOW_TIMEOUT_MESSAGE_AFTER)
            )
            actions.setIsLoading(true)
        },
        abortQuery: ({ queryId, view, scene, exception }) => {
            const duration = new Date().getTime() - values.queryStartTimes[queryId]
            const tags = {
                insight: view,
                scene: scene,
                success: !exception,
                ...exception,
            }

            posthog.capture('insight aborted', { ...tags, duration })
            captureInternalMetric({ method: 'timing', metric: 'insight_abort_time', value: duration, tags })
        },
        endQuery: ({ queryId, view, lastRefresh, exception }) => {
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            if (view === values.activeView) {
                actions.setShowTimeoutMessage(values.maybeShowTimeoutMessage)
                actions.setShowErrorMessage(values.maybeShowErrorMessage)
                actions.setLastRefresh(lastRefresh || null)
                actions.setIsLoading(false)

                const duration = new Date().getTime() - values.queryStartTimes[queryId]
                const tags = {
                    insight: values.activeView,
                    scene: sceneLogic.isMounted() ? sceneLogic.values.scene : null,
                    success: !exception,
                    ...exception,
                }

                posthog.capture('insight loaded', { ...tags, duration })
                captureInternalMetric({ method: 'timing', metric: 'insight_load_time', value: duration, tags })
                if (values.maybeShowErrorMessage) {
                    posthog.capture('insight error message shown', { ...tags, duration })
                }
            }
        },
        setActiveView: ({ type }) => {
            actions.setFilters(cleanFilters({ ...values.filters, insight: type as InsightType }, values.filters))
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
        },
        saveNewTag: async ({ tag }) => {
            if (values.insight.tags?.includes(tag)) {
                errorToast(undefined, 'Oops! Your insight already has that tag.')
                return
            }
            actions.setInsightMetadata({ tags: [...(values.insight.tags || []), tag] })
        },
        deleteTag: async ({ tag }) => {
            actions.setInsightMetadata({ tags: values.insight.tags?.filter((_tag) => _tag !== tag) })
        },
        saveInsight: async ({ setViewMode }) => {
            const insightId =
                values.insight.id || (values.insight.short_id ? await getInsightId(values.insight.short_id) : undefined)
            if (!insightId) {
                throw new Error('Can only save saved insights whose id is known.')
            }
            const savedInsight: DashboardItemType = await api.update(
                `api/projects/${teamLogic.values.currentTeamId}/insights/${insightId}`,
                { ...values.insight, saved: true }
            )
            actions.setInsight(
                { ...savedInsight, result: savedInsight.result || values.insight.result },
                { fromPersistentApi: true }
            )
            if (setViewMode) {
                actions.setInsightMode(ItemMode.View, InsightEventSource.InsightHeader)
            }
            toast(
                <div data-attr="success-toast">
                    Insight saved!&nbsp;
                    <Link to={urls.savedInsights()}>Click here to see your list of saved insights</Link>
                </div>
            )
            savedInsightsLogic.findMounted()?.actions.loadInsights()
            dashboardsModel.actions.updateDashboardItem(savedInsight)
        },
        saveAs: async () => {
            prompt({ key: `save-as-insight` }).actions.prompt({
                title: 'Save as new insight',
                placeholder: 'Please enter the new name',
                value: values.insight.name + ' (copy)',
                error: 'You must enter a name',
                success: actions.saveAsNamingSuccess,
            })
        },
        saveAsNamingSuccess: async ({ name }) => {
            const insight: DashboardItemType = await api.create(
                `api/projects/${teamLogic.values.currentTeamId}/insights/`,
                {
                    name,
                    filters: values.filters,
                    saved: true,
                }
            )
            toast(`You're now working on a copy of ${values.insight.name}`)
            actions.setInsight(insight, { fromPersistentApi: true })
            savedInsightsLogic.findMounted()?.actions.loadInsights()
            if (values.syncWithUrl) {
                router.actions.push(urls.insightEdit(insight.short_id, values.filters))
            }
        },
        loadInsightSuccess: async ({ payload, insight }) => {
            actions.reportInsightViewed(insight?.filters || {})
            // loaded `/api/projects/:id/insights`, but it didn't have `results`, so make another query
            if (!insight.result && values.filters && !payload?.doNotLoadResults) {
                actions.loadResults()
            }
        },
        // called when search query was successful
        loadResultsSuccess: async ({ insight }, breakpoint) => {
            if (props.doNotPersist) {
                return
            }
            if (!insight.short_id) {
                const createdInsight: DashboardItemType = await api.create(
                    `api/projects/${values.currentTeamId}/insights`,
                    {
                        filters: insight.filters,
                    }
                )
                breakpoint()
                actions.setInsight(
                    { ...insight, ...createdInsight, result: createdInsight.result || insight.result },
                    {}
                )
                if (values.syncWithUrl) {
                    router.actions.replace(
                        values.insightMode === ItemMode.Edit
                            ? urls.insightEdit(createdInsight.short_id, values.filters)
                            : urls.insightView(createdInsight.short_id, values.filters)
                    )
                }
            }
        },
        createAndRedirectToNewInsight: async ({ filters }, breakpoint) => {
            const newInsight = {
                name: generateRandomAnimal(),
                description: '',
                tags: [],
                filters: cleanFilters(filters || {}),
                result: null,
            }
            const createdInsight: DashboardItemType = await api.create(
                `api/projects/${teamLogic.values.currentTeamId}/insights`,
                newInsight
            )
            breakpoint()
            eventUsageLogic.actions.reportInsightCreated(filters?.insight || null)
            router.actions.replace(
                urls.insightEdit(createdInsight.short_id, cleanFilters(createdInsight.filters || filters || {}))
            )
        },
    }),
    actionToUrl: ({ values }) => {
        const actionToUrl = (): [string, undefined, undefined, { replace: boolean }] | void => {
            if (values.syncWithUrl && values.insight.short_id) {
                return [
                    values.insightMode === ItemMode.Edit
                        ? urls.insightEdit(values.insight.short_id, values.filters)
                        : urls.insightView(values.insight.short_id, values.filters),
                    undefined,
                    undefined,
                    { replace: true },
                ]
            }
        }
        return {
            setFilters: actionToUrl,
            setInsightMode: actionToUrl,
        }
    },
    urlToAction: ({ actions, values }) => ({
        '/insights/:shortId(/:mode)': (params, searchParams, hashParams) => {
            if (values.syncWithUrl) {
                if (searchParams.insight === 'HISTORY') {
                    // Legacy redirect because the insight history scene was toggled via the insight type.
                    router.actions.replace(urls.savedInsights())
                    return
                }
                if (params.shortId === 'new') {
                    actions.createAndRedirectToNewInsight(searchParams)
                    return
                }
                const insightId = params.shortId ? (String(params.shortId) as InsightShortId) : null
                if (!insightId) {
                    // only allow editing insights with IDs for now
                    router.actions.replace(urls.insightNew(searchParams))
                    return
                }

                let loadedFromAnotherLogic = false
                const insightIdChanged = !values.insight.short_id || values.insight.short_id !== insightId

                if (!values.insight.result || insightIdChanged) {
                    const insight = findInsightFromMountedLogic(insightId, hashParams.fromDashboard)
                    if (insight) {
                        actions.setInsight(insight, { overrideFilter: true, fromPersistentApi: true })
                        if (insight?.result) {
                            loadedFromAnotherLogic = true
                        }
                    }
                }

                if (!loadedFromAnotherLogic && insightIdChanged) {
                    // Do not load the result if missing, as setFilters below will do so anyway.
                    actions.loadInsight(insightId, { doNotLoadResults: true })
                }

                const cleanSearchParams = cleanFilters(searchParams, values.filters, values.featureFlags)
                const insightModeFromUrl = params['mode'] === 'edit' ? ItemMode.Edit : ItemMode.View

                if (
                    (!loadedFromAnotherLogic && !objectsEqual(cleanSearchParams, values.filters)) ||
                    insightModeFromUrl !== values.insightMode
                ) {
                    actions.setFilters(cleanSearchParams, insightModeFromUrl)
                }
            }
        },
    }),
    events: ({ actions, cache, props, values }) => ({
        afterMount: () => {
            if (!props.cachedResults) {
                if (props.dashboardItemId && !props.filters) {
                    const insight = findInsightFromMountedLogic(
                        props.dashboardItemId,
                        router.values.hashParams.fromDashboard
                    )
                    if (insight) {
                        actions.setInsight(insight, { overrideFilter: true, fromPersistentApi: true })
                        if (insight?.result) {
                            return
                        }
                    }
                    actions.loadInsight(props.dashboardItemId)
                } else if (!props.doNotLoad) {
                    actions.loadResults()
                }
            }
        },
        beforeUnmount: () => {
            cache.abortController?.abort()
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            toast.dismiss()
        },
    }),
})
