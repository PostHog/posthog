import { captureException } from '@sentry/react'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { DashboardPrivilegeLevel, FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { summarizeInsight } from 'scenes/insights/summarizeInsight'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupsModel } from '~/models/groupsModel'
import { insightsModel } from '~/models/insightsModel'
import { tagsModel } from '~/models/tagsModel'
import { getInsightFilterOrQueryForPersistance } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightVizNode } from '~/queries/schema'
import {
    FilterType,
    InsightLogicProps,
    InsightModel,
    InsightShortId,
    ItemMode,
    QueryBasedInsightModel,
    SetInsightOptions,
} from '~/types'

import { teamLogic } from '../teamLogic'
import type { insightLogicType } from './insightLogicType'
import { getInsightId } from './utils'

export const UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES = 3

function emptyFilters(filters: Partial<FilterType> | undefined): boolean {
    return (
        !filters ||
        (Object.keys(filters).length < 2 && JSON.stringify(cleanFilters(filters)) === JSON.stringify(cleanFilters({})))
    )
}

export const createEmptyInsight = (
    insightId: InsightShortId | `new-${string}` | 'new',
    filterTestAccounts: boolean
): Partial<InsightModel> => ({
    short_id: insightId !== 'new' && !insightId.startsWith('new-') ? (insightId as InsightShortId) : undefined,
    name: '',
    description: '',
    tags: [],
    filters: filterTestAccounts ? { filter_test_accounts: true } : {},
    result: null,
})

export const insightLogic = kea<insightLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightLogic', key]),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId', 'currentTeam'],
            groupsModel,
            ['aggregationLabel'],
            cohortsModel,
            ['cohortsById'],
            mathsLogic,
            ['mathDefinitions'],
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [tagsModel, ['loadTags']],
        logic: [eventUsageLogic, dashboardsModel],
    })),

    actions({
        setFilters: (filters: Partial<FilterType>, insightMode?: ItemMode, clearInsightQuery?: boolean) => ({
            filters,
            insightMode,
            clearInsightQuery,
        }),
        setInsight: (insight: Partial<InsightModel>, options: SetInsightOptions) => ({
            insight,
            options,
        }),
        saveAsNamingSuccess: (name: string, redirectToViewMode?: boolean) => ({ name, redirectToViewMode }),
        cancelChanges: true,
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        saveInsightSuccess: true,
        saveInsightFailure: true,
        loadInsight: (shortId: InsightShortId) => ({
            shortId,
        }),
        updateInsight: (insight: Partial<InsightModel>, callback?: (insight: Partial<InsightModel>) => void) => ({
            insight,
            callback,
        }),
        setInsightMetadata: (metadata: Partial<InsightModel>) => ({ metadata }),
        highlightSeries: (seriesIndex: number | null) => ({ seriesIndex }),
    }),
    loaders(({ actions, values, props }) => ({
        legacyInsight: [
            props.cachedInsight ??
                createEmptyInsight(
                    props.dashboardItemId || 'new',
                    values.currentTeam?.test_account_filters_default_checked || false
                ),
            {
                loadInsight: async ({ shortId }, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.insights.loadInsight(shortId, undefined, 'async')
                    if (response?.results?.[0]) {
                        return response.results[0]
                    }
                    throw new Error(`Insight "${shortId}" not found`)
                },
                updateInsight: async ({ insight, callback }, breakpoint) => {
                    if (!Object.entries(insight).length) {
                        return values.legacyInsight
                    }

                    if ('filters' in insight && !insight.query && emptyFilters(insight.filters)) {
                        const error = new Error('Will not override empty filters in updateInsight.')
                        captureException(error, {
                            extra: {
                                filters: JSON.stringify(insight.filters),
                                insight: JSON.stringify(insight),
                                valuesInsight: JSON.stringify(values.legacyInsight),
                            },
                        })
                        throw error
                    }

                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.legacyInsight.id}`,
                        insight
                    )
                    breakpoint()
                    const updatedInsight: InsightModel = {
                        ...response,
                        result: response.result || values.legacyInsight.result,
                    }
                    callback?.(updatedInsight)

                    const removedDashboards = (values.legacyInsight.dashboards || []).filter(
                        (d) => !updatedInsight.dashboards?.includes(d)
                    )
                    dashboardsModel.actions.updateDashboardInsight(updatedInsight, removedDashboards)
                    return updatedInsight
                },
                setInsightMetadata: async ({ metadata }, breakpoint) => {
                    const editMode =
                        insightSceneLogic.isMounted() &&
                        insightSceneLogic.values.legacyInsight === values.legacyInsight &&
                        insightSceneLogic.values.insightMode === ItemMode.Edit

                    if (editMode) {
                        return { ...values.legacyInsight, ...metadata }
                    }

                    if (metadata.filters || metadata.query) {
                        const error = new Error(`Will not override filters or query in setInsightMetadata`)
                        captureException(error)
                        throw error
                    }

                    const beforeUpdates = {}
                    for (const key of Object.keys(metadata)) {
                        beforeUpdates[key] = values.savedInsight[key]
                    }

                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.legacyInsight.id}`,
                        metadata
                    )
                    breakpoint()

                    // only update the fields that we changed
                    const updatedInsight = { ...values.legacyInsight } as InsightModel
                    for (const key of Object.keys(metadata)) {
                        updatedInsight[key] = response[key]
                    }

                    savedInsightsLogic.findMounted()?.actions.loadInsights()
                    dashboardsModel.actions.updateDashboardInsight(updatedInsight)
                    actions.loadTags()

                    lemonToast.success(`Updated insight`, {
                        button: {
                            label: 'Undo',
                            dataAttr: 'edit-insight-undo',
                            action: async () => {
                                const response = await api.update(
                                    `api/projects/${teamLogic.values.currentTeamId}/insights/${values.queryBasedInsight.id}`,
                                    beforeUpdates
                                )
                                // only update the fields that we changed
                                const revertedInsight = { ...values.legacyInsight } as InsightModel
                                for (const key of Object.keys(beforeUpdates)) {
                                    revertedInsight[key] = response[key]
                                }
                                savedInsightsLogic.findMounted()?.actions.loadInsights()
                                dashboardsModel.actions.updateDashboardInsight(revertedInsight)
                                actions.setInsight(revertedInsight, { overrideFilter: false, fromPersistentApi: true })
                                lemonToast.success('Insight change reverted')
                            },
                        },
                    })
                    return updatedInsight
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        highlightedSeries: [
            null as number | null,
            {
                highlightSeries: (_, { seriesIndex }) => seriesIndex,
            },
        ],
        legacyInsight: {
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
            setInsight: (_state, { insight }) => ({
                ...insight,
            }),
            setFilters: (state, { clearInsightQuery }) => {
                return {
                    ...state,
                    query: clearInsightQuery ? undefined : state.query,
                }
            },
            setInsightMetadata: (state, { metadata }) => ({ ...state, ...metadata }),
            [dashboardsModel.actionTypes.updateDashboardInsight]: (state, { item, extraDashboardIds }) => {
                const targetDashboards = (item?.dashboards || []).concat(extraDashboardIds || [])
                const updateIsForThisDashboard =
                    item?.short_id === state.short_id &&
                    props.dashboardId &&
                    targetDashboards.includes(props.dashboardId)
                if (updateIsForThisDashboard) {
                    return { ...state, ...item }
                }
                return state
            },
            [insightsModel.actionTypes.renameInsightSuccess]: (state, { item }) => {
                if (item.id === state.id) {
                    return { ...state, name: item.name }
                }
                return state
            },
            [insightsModel.actionTypes.insightsAddedToDashboard]: (state, { dashboardId, insightIds }) => {
                if (insightIds.includes(state.id)) {
                    return { ...state, dashboards: [...(state.dashboards || []), dashboardId] }
                }
                return state
            },
            [dashboardsModel.actionTypes.tileRemovedFromDashboard]: (state, { tile, dashboardId }) => {
                if (tile.insight?.id === state.id) {
                    return { ...state, dashboards: state.dashboards?.filter((d) => d !== dashboardId) }
                }
                return state
            },
            [dashboardsModel.actionTypes.deleteDashboardSuccess]: (state, { dashboard }) => {
                const { id } = dashboard
                return { ...state, dashboards: state.dashboards?.filter((d) => d !== id) }
            },
        },
        /** The insight's state as it is in the database. */
        savedInsight: [
            () => props.cachedInsight || ({} as InsightModel),
            {
                setInsight: (state, { insight, options: { fromPersistentApi } }) =>
                    fromPersistentApi ? { ...insight, filters: cleanFilters(insight.filters || {}) } : state,
                loadInsightSuccess: (_, { legacyInsight }) => ({
                    ...legacyInsight,
                    filters: cleanFilters(legacyInsight.filters || {}),
                }),
                updateInsightSuccess: (_, { legacyInsight }) => ({
                    ...legacyInsight,
                    filters: cleanFilters(legacyInsight.filters || {}),
                }),
            },
        ],
        insightLoading: [
            false,
            {
                loadInsight: () => true,
                loadInsightSuccess: () => false,
                loadInsightFailure: () => false,
            },
        ],
        insightSaving: [
            false,
            {
                saveInsight: () => true,
                saveInsightSuccess: () => false,
                saveInsightFailure: () => false,
            },
        ],
    })),
    selectors({
        queryBasedInsightSaving: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.QUERY_BASED_INSIGHTS_SAVING],
        ],
        queryBasedInsight: [
            (s) => [s.legacyInsight],
            (legacyInsight) => getQueryBasedInsightModel(legacyInsight) as QueryBasedInsightModel,
        ],
        insightProps: [() => [(_, props) => props], (props): InsightLogicProps => props],
        isInDashboardContext: [() => [(_, props) => props], ({ dashboardId }) => !!dashboardId],
        hasDashboardItemId: [
            () => [(_, props) => props],
            (props: InsightLogicProps) =>
                !!props.dashboardItemId && props.dashboardItemId !== 'new' && !props.dashboardItemId.startsWith('new-'),
        ],
        isInExperimentContext: [
            () => [router.selectors.location],
            ({ pathname }) => /^.*\/experiments\/\d+$/.test(pathname),
        ],
        derivedName: [
            (s) => [s.queryBasedInsight, s.aggregationLabel, s.cohortsById, s.mathDefinitions],
            (insight, aggregationLabel, cohortsById, mathDefinitions) =>
                summarizeInsight(insight.query, {
                    aggregationLabel,
                    cohortsById,
                    mathDefinitions,
                }).slice(0, 400),
        ],
        insightName: [
            (s) => [s.queryBasedInsight, s.derivedName],
            (insight, derivedName) => insight.name || derivedName,
        ],
        insightId: [(s) => [s.queryBasedInsight], (insight) => insight?.id || null],
        isQueryBasedInsight: [(s) => [s.legacyInsight], (insight) => !!insight.query],
        canEditInsight: [
            (s) => [s.queryBasedInsight],
            (insight) =>
                insight.effective_privilege_level == undefined ||
                insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit,
        ],
        insightChanged: [
            (s) => [s.queryBasedInsight, s.savedInsight],
            (insight, savedInsight): boolean => {
                return (
                    (insight.name || '') !== (savedInsight.name || '') ||
                    (insight.description || '') !== (savedInsight.description || '') ||
                    !objectsEqual(insight.tags || [], savedInsight.tags || [])
                )
            },
        ],
        showPersonsModal: [() => [(_, p) => p.query], (query?: InsightVizNode) => !query || !query.hidePersonsModal],
    }),
    listeners(({ actions, values }) => ({
        saveInsight: async ({ redirectToViewMode }) => {
            const insightNumericId =
                values.queryBasedInsight.id ||
                (values.queryBasedInsight.short_id ? await getInsightId(values.queryBasedInsight.short_id) : undefined)
            const { name, description, favorited, deleted, dashboards, tags } = values.legacyInsight

            let savedInsight: InsightModel
            const { filters, query } = getInsightFilterOrQueryForPersistance(
                values.queryBasedInsight,
                values.queryBasedInsightSaving
            )

            try {
                // We don't want to send ALL the insight properties back to the API, so only grabbing fields that might have changed
                const insightRequest: Partial<InsightModel> = {
                    name,
                    derived_name: values.derivedName,
                    description,
                    favorited,
                    filters,
                    query,
                    deleted,
                    saved: true,
                    dashboards,
                    tags,
                }

                savedInsight = insightNumericId
                    ? await api.update(
                          `api/projects/${teamLogic.values.currentTeamId}/insights/${insightNumericId}`,
                          insightRequest
                      )
                    : await api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/`, insightRequest)
                savedInsightsLogic.findMounted()?.actions.loadInsights() // Load insights afresh
                actions.saveInsightSuccess()
            } catch (e) {
                actions.saveInsightFailure()
                throw e
            }

            // the backend can't return the result for a query based insight,
            // and so we shouldn't copy the result from `values.insight` as it might be stale
            const result = savedInsight.result || (query ? values.legacyInsight.result : null)
            actions.setInsight({ ...savedInsight, result: result }, { fromPersistentApi: true, overrideFilter: true })
            eventUsageLogic.actions.reportInsightSaved(filters || {}, insightNumericId === undefined)
            lemonToast.success(`Insight saved${dashboards?.length === 1 ? ' & added to dashboard' : ''}`, {
                button: {
                    label: 'View Insights list',
                    action: () => router.actions.push(urls.savedInsights()),
                },
            })

            dashboardsModel.actions.updateDashboardInsight(savedInsight)

            // reload dashboards with updated insight
            // since filters on dashboard might be different from filters on insight
            // we need to trigger dashboard reload to pick up results for updated insight
            savedInsight.dashboard_tiles?.forEach(({ dashboard_id }) =>
                dashboardLogic.findMounted({ id: dashboard_id })?.actions.loadDashboard({
                    action: 'update',
                    refresh: 'lazy_async',
                })
            )

            const mountedInsightSceneLogic = insightSceneLogic.findMounted()
            if (redirectToViewMode) {
                if (!insightNumericId && dashboards?.length === 1) {
                    // redirect new insights added to dashboard to the dashboard
                    router.actions.push(urls.dashboard(dashboards[0], savedInsight.short_id))
                } else if (insightNumericId) {
                    mountedInsightSceneLogic?.actions.setInsightMode(ItemMode.View, InsightEventSource.InsightHeader)
                } else {
                    router.actions.push(urls.insightView(savedInsight.short_id))
                }
            } else if (!insightNumericId) {
                // If we've just saved a new insight without redirecting to view mode, we need to redirect to edit mode
                // so that we aren't stuck on /insights/new
                router.actions.push(urls.insightEdit(savedInsight.short_id))
            }
        },
        saveAsNamingSuccess: async ({ name, redirectToViewMode }) => {
            const { filters, query } = getInsightFilterOrQueryForPersistance(
                values.queryBasedInsight,
                values.queryBasedInsightSaving
            )
            const insight: InsightModel = await api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/`, {
                name,
                filters,
                query,
                saved: true,
            })
            lemonToast.info(
                `You're now working on a copy of ${
                    values.queryBasedInsight.name || values.queryBasedInsight.derived_name || name
                }`
            )
            actions.setInsight(insight, { fromPersistentApi: true, overrideFilter: true })
            savedInsightsLogic.findMounted()?.actions.loadInsights() // Load insights afresh

            if (redirectToViewMode) {
                router.actions.push(urls.insightView(insight.short_id))
            } else {
                router.actions.push(urls.insightEdit(insight.short_id))
            }
        },
        cancelChanges: () => {
            actions.setFilters(values.savedInsight.filters || {})
        },
    })),
    events(({ props, actions }) => ({
        afterMount: () => {
            if (!props.dashboardItemId || props.dashboardItemId === 'new' || props.dashboardItemId.startsWith('new-')) {
                return
            }

            if (!props.doNotLoad && !props.cachedInsight) {
                actions.loadInsight(props.dashboardItemId as InsightShortId)
            }
        },
    })),
])
