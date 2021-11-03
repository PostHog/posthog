import { kea } from 'kea'
import { errorToast, objectsEqual, toParams, uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from './insightLogicType'
import {
    AvailableFeature,
    DashboardItemType,
    FilterType,
    InsightLogicProps,
    InsightType,
    ItemMode,
    SetInsightOptions,
    ViewType,
} from '~/types'
import { captureInternalMetric } from 'lib/internalMetrics'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import React from 'react'
import { Link } from 'lib/components/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { filterTrendsClientSideParams, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { dashboardsModel } from '~/models/dashboardsModel'
import { pollFunnel } from 'scenes/funnels/funnelUtils'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { extractObjectDiffKeys, findInsightFromMountedLogic } from './utils'
import * as Sentry from '@sentry/browser'
import { teamLogic } from '../teamLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { sceneLogic } from 'scenes/sceneLogic'

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

    connect: {
        values: [teamLogic, ['currentTeamId']],
        logic: [eventUsageLogic, dashboardsModel, featureFlagLogic],
    },

    actions: () => ({
        setActiveView: (type: ViewType) => ({ type }),
        updateActiveView: (type: ViewType) => ({ type }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        startQuery: (queryId: string) => ({ queryId }),
        endQuery: (queryId: string, view: ViewType, lastRefresh: string | null, exception?: Record<string, any>) => ({
            queryId,
            view,
            lastRefresh,
            exception,
        }),
        abortQuery: (queryId: string, view: ViewType, scene: Scene | null, exception?: Record<string, any>) => ({
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
        toggleControlsCollapsed: true,
        saveNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        setInsight: (insight: Partial<DashboardItemType>, options: SetInsightOptions) => ({
            insight,
            options,
        }),
        setInsightMode: (mode: ItemMode, source: InsightEventSource | null) => ({ mode, source }),
        setInsightDescription: (description: string) => ({ description }),
        saveInsight: true,
        setTagLoading: (tagLoading: boolean) => ({ tagLoading }),
        fetchedResults: (filters: Partial<FilterType>) => ({ filters }),
        loadInsight: (id: number, { doNotLoadResults }: { doNotLoadResults?: boolean } = {}) => ({
            id,
            doNotLoadResults,
        }),
        updateInsight: (
            insight: Partial<DashboardItemType>,
            callback?: (insight: Partial<DashboardItemType>) => void
        ) => ({ insight, callback }),
        loadResults: (refresh = false) => ({ refresh, queryId: uuid() }),
        setInsightMetadata: (metadata: Partial<DashboardItemType>) => ({ metadata }),
    }),
    loaders: ({ actions, cache, values, props }) => ({
        insight: [
            {
                id: props.dashboardItemId,
                tags: [],
                filters: props.cachedResults ? props.filters || {} : {},
                result: props.cachedResults || null,
            } as Partial<DashboardItemType>,
            {
                loadInsight: async ({ id }) => {
                    return await api.get(`api/projects/${teamLogic.values.currentTeamId}/insights/${id}`)
                },
                updateInsight: async ({ insight, callback }, breakpoint) => {
                    if (!Object.entries(insight).length) {
                        return
                    }
                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                        insight
                    )
                    breakpoint()
                    const updatedInsight = { ...response, result: response.result || values.insight.result }
                    callback?.(updatedInsight)
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
                    const insight = (filters.insight as ViewType | undefined) || ViewType.TRENDS
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
                            insight === ViewType.TRENDS ||
                            insight === ViewType.STICKINESS ||
                            insight === ViewType.LIFECYCLE
                        ) {
                            response = await api.get(
                                `api/projects/${currentTeamId}/insights/trend/?${toParams(
                                    filterTrendsClientSideParams(params)
                                )}`,
                                cache.abortController.signal
                            )
                        } else if (insight === ViewType.SESSIONS || filters?.session) {
                            response = await api.get(
                                `api/projects/${currentTeamId}/insights/session/?${toParams(
                                    filterTrendsClientSideParams(params)
                                )}`,
                                cache.abortController.signal
                            )
                        } else if (insight === ViewType.RETENTION) {
                            response = await api.get(
                                `api/projects/${currentTeamId}/insights/retention/?${toParams(params)}`,
                                cache.abortController.signal
                            )
                        } else if (insight === ViewType.FUNNELS) {
                            response = await pollFunnel(currentTeamId, params)
                        } else if (insight === ViewType.PATHS) {
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
                        if (filters.insight === ViewType.FUNNELS) {
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
                        (values.filters.insight as ViewType) || ViewType.TRENDS,
                        response.last_refresh
                    )
                    if (dashboardItemId && dashboardsModel.isMounted()) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(
                            dashboardItemId,
                            false,
                            response.last_refresh
                        )
                    }
                    if (filters.insight === ViewType.FUNNELS) {
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
            loadInsight: (state, { id }) =>
                id === state.id
                    ? state
                    : {
                          // blank slate if switched to a new insight
                          id,
                          tags: [],
                          result: null,
                          filters: {},
                      },
            setInsight: (state, { insight, options: { shouldMergeWithExisting } }) => ({
                ...(shouldMergeWithExisting ? state : {}),
                ...insight,
            }),
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
        controlsCollapsed: [
            false,
            {
                toggleControlsCollapsed: (state) => !state,
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
        activeView: [(s) => [s.filters], (filters) => filters.insight || ViewType.TRENDS],
        loadedView: [
            (s) => [s.insight, s.activeView],
            ({ filters }, activeView) => filters?.insight || activeView || ViewType.TRENDS,
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
            () => [featureFlagLogic.selectors.featureFlags, userLogic.selectors.user],
            (featureFlags, user) =>
                !!(
                    featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] &&
                    user?.organization?.available_features?.includes(AvailableFeature.DASHBOARD_COLLABORATION)
                ),
        ],
    },
    listeners: ({ actions, selectors, values, props }) => ({
        setFilters: async ({ filters }, breakpoint, _, previousState) => {
            const { fromDashboard } = router.values.hashParams
            const previousFilters = selectors.filters(previousState)
            if (objectsEqual(previousFilters, filters)) {
                return
            }

            const changedKeysObj: Record<string, any> = extractObjectDiffKeys(previousFilters, filters)

            eventUsageLogic.actions.reportInsightViewed(
                filters,
                values.isFirstLoad,
                Boolean(fromDashboard),
                0,
                changedKeysObj
            )
            actions.setNotFirstLoad()

            const filterLength = (filter?: Partial<FilterType>): number =>
                (filter?.events?.length || 0) + (filter?.actions?.length || 0)

            const insightChanged = values.loadedFilters?.insight && filters.insight !== values.loadedFilters?.insight

            const backendFilterChanged = !objectsEqual(
                Object.assign({}, values.filters, { layout: undefined, hiddenLegendKeys: undefined }),
                Object.assign({}, values.loadedFilters, { layout: undefined, hiddenLegendKeys: undefined })
            )

            // Auto-reload when setting filters
            if (
                backendFilterChanged &&
                (values.filters.insight !== ViewType.FUNNELS ||
                    // Auto-reload on funnels if with clickhouse
                    values.clickhouseFeaturesEnabled ||
                    // Or if tabbing to the funnels insight
                    insightChanged ||
                    // If user started from empty state (<2 steps) and added a new step
                    (filterLength(values.loadedFilters) === 1 && filterLength(values.filters) === 2))
            ) {
                actions.loadResults()
            }

            // tests will wait for all breakpoints to finish
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportInsightViewed(
                filters,
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
        toggleControlsCollapsed: async () => {
            eventUsageLogic.actions.reportInsightsControlsCollapseToggle(values.controlsCollapsed)
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
        saveInsight: async () => {
            const savedInsight = await api.update(
                `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                {
                    ...values.insight,
                    saved: true,
                }
            )
            actions.setInsight(
                { ...savedInsight, result: savedInsight.result || values.insight.result },
                { fromPersistentApi: true }
            )
            actions.setInsightMode(ItemMode.View, InsightEventSource.InsightHeader)
            toast(
                <div data-attr="success-toast">
                    Insight saved!&nbsp;
                    <Link to={'/saved_insights'}>Click here to see your list of saved insights</Link>
                </div>
            )
        },
        loadInsightSuccess: async ({ payload, insight }) => {
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
            if (!insight.id) {
                const createdInsight = await api.create(`api/projects/${values.currentTeamId}/insights`, {
                    filters: insight.filters,
                })
                breakpoint()
                actions.setInsight(
                    { ...insight, ...createdInsight, result: createdInsight.result || insight.result },
                    {}
                )
                if (props.syncWithUrl) {
                    router.actions.replace('/insights', router.values.searchParams, {
                        ...router.values.hashParams,
                        fromItem: createdInsight.id,
                    })
                }
            } else if (insight.filters) {
                // This auto-saves new filters into the insight.
                // Exceptions:
                if (
                    // - not saved if "saved insights" feature flag is enabled
                    !featureFlagLogic.values.featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] &&
                    // - not saved if on the history "insight" for some reason
                    (insight.filters.insight as ViewType) !== ViewType.HISTORY &&
                    // - not saved if we came from a dashboard --> there's a separate "save" button for that
                    !router.values.hashParams.fromDashboard &&
                    // - not saved if we come from the "saved funnels" list, TO BE REMOVED with release of "3408-saved-insights"
                    !router.values.hashParams.fromSavedFunnels
                ) {
                    const filterLength = Object.keys(insight.filters).length
                    if (filterLength === 0 || (filterLength === 1 && 'from_dashboard' in insight.filters)) {
                        Sentry.captureException(
                            new Error(
                                filterLength === 0
                                    ? 'Would save empty filters'
                                    : `Would save filters with just "from_dashboard"`
                            ),
                            {
                                extra: {
                                    filters_to_save: JSON.stringify(insight.filters),
                                    insight: JSON.stringify(insight),
                                    filters: JSON.stringify(values.filters),
                                },
                            }
                        )
                    } else {
                        actions.updateInsight({ filters: insight.filters })
                    }
                }
            }
        },
        setInsightMetadata: ({ metadata }) => {
            if (values.insightMode === ItemMode.Edit) {
                actions.setInsight(metadata, { shouldMergeWithExisting: true })
            } else {
                actions.updateInsight(metadata)
            }
        },
    }),
    actionToUrl: ({ values, props }) => ({
        setFilters: () => {
            if (props.syncWithUrl) {
                return ['/insights', values.filters, router.values.hashParams, { replace: true }]
            }
        },
        setInsightMode: () => {
            if (props.syncWithUrl) {
                // eslint-disable-next-line @typescript-eslint/no-unused-vars
                const { edit: _discard, ...otherHashParams } = router.values.hashParams
                return [
                    '/insights',
                    router.values.searchParams,
                    values.insightMode === ItemMode.View ? otherHashParams : { ...otherHashParams, edit: true },
                    { replace: true },
                ]
            }
        },
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/insights': (_: any, searchParams: Record<string, any>, hashParams: Record<string, any>) => {
            if (props.syncWithUrl) {
                let loadedFromAnotherLogic = false
                if (searchParams.insight === 'HISTORY' || !hashParams.fromItem) {
                    if (values.insightMode !== ItemMode.Edit) {
                        actions.setInsightMode(ItemMode.Edit, null)
                    }
                } else if (hashParams.fromItem) {
                    const insightIdChanged = !values.insight.id || values.insight.id !== hashParams.fromItem

                    if (
                        featureFlagLogic.values.featureFlags[FEATURE_FLAGS.TURBO_MODE] &&
                        (!values.insight.result || insightIdChanged)
                    ) {
                        const insight = findInsightFromMountedLogic(hashParams.fromItem, hashParams.fromDashboard)
                        if (insight) {
                            actions.setInsight(insight, { overrideFilter: true, fromPersistentApi: true })
                            if (insight?.result) {
                                loadedFromAnotherLogic = true
                            }
                        }
                    }

                    if (!loadedFromAnotherLogic && insightIdChanged) {
                        // Do not load the result if missing, as setFilters below will do so anyway.
                        actions.loadInsight(hashParams.fromItem, { doNotLoadResults: true })
                    }

                    const insightModeFromUrl = hashParams.edit ? ItemMode.Edit : ItemMode.View
                    if (insightModeFromUrl !== values.insightMode) {
                        actions.setInsightMode(insightModeFromUrl, null)
                    }
                }

                const cleanSearchParams = cleanFilters(searchParams, values.filters)
                if (!loadedFromAnotherLogic && !objectsEqual(cleanSearchParams, values.filters)) {
                    actions.setFilters(cleanSearchParams)
                }
            }
        },
    }),
    events: ({ actions, cache, props, values }) => ({
        afterMount: () => {
            if (!props.cachedResults) {
                if (props.dashboardItemId && !props.filters) {
                    if (featureFlagLogic.values.featureFlags[FEATURE_FLAGS.TURBO_MODE]) {
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
