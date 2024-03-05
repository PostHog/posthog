import { captureException } from '@sentry/react'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { parseProperties } from 'lib/components/PropertyFilters/utils'
import { DashboardPrivilegeLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getEventNamesForAction, objectsEqual, sum, toParams } from 'lib/utils'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { transformLegacyHiddenLegendKeys } from 'scenes/funnels/funnelUtils'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import {
    filterTrendsClientSideParams,
    isFilterWithHiddenLegendKeys,
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
    keyForInsightLogicProps,
} from 'scenes/insights/sharedUtils'
import { summarizeInsight } from 'scenes/insights/summarizeInsight'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupsModel } from '~/models/groupsModel'
import { insightsModel } from '~/models/insightsModel'
import { tagsModel } from '~/models/tagsModel'
import { queryExportContext } from '~/queries/query'
import { InsightVizNode } from '~/queries/schema'
import { isInsightVizNode } from '~/queries/utils'
import {
    ActionType,
    FilterType,
    InsightLogicProps,
    InsightModel,
    InsightShortId,
    ItemMode,
    SetInsightOptions,
    TrendsFilterType,
} from '~/types'

import { teamLogic } from '../teamLogic'
import { toLocalFilters } from './filters/ActionFilter/entityFilterLogic'
import type { insightLogicType } from './insightLogicType'
import { extractObjectDiffKeys, findInsightFromMountedLogic, getInsightId } from './utils'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
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
        setFiltersMerge: (filters: Partial<FilterType>) => ({ filters }),
        reportInsightViewedForRecentInsights: () => true,
        reportInsightViewed: (
            insightModel: Partial<InsightModel>,
            filters: Partial<FilterType>,
            previousFilters?: Partial<FilterType>
        ) => ({
            insightModel,
            filters,
            previousFilters,
        }),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setNotFirstLoad: true,
        setInsight: (insight: Partial<InsightModel>, options: SetInsightOptions) => ({
            insight,
            options,
        }),
        saveAsNamingSuccess: (name: string) => ({ name }),
        cancelChanges: true,
        setInsightDescription: (description: string) => ({ description }),
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
        toggleVisibility: (index: number) => ({ index }),
        highlightSeries: (seriesIndex: number | null) => ({ seriesIndex }),
    }),
    loaders(({ actions, values, props }) => ({
        insight: [
            props.cachedInsight ??
                createEmptyInsight(
                    props.dashboardItemId || 'new',
                    values.currentTeam?.test_account_filters_default_checked || false
                ),
            {
                loadInsight: async ({ shortId }) => {
                    const response = await api.insights.loadInsight(shortId)
                    if (response?.results?.[0]) {
                        return response.results[0]
                    }
                    throw new Error(`Insight "${shortId}" not found`)
                },
                updateInsight: async ({ insight, callback }, breakpoint) => {
                    if (!Object.entries(insight).length) {
                        return values.insight
                    }

                    if ('filters' in insight && !insight.query && emptyFilters(insight.filters)) {
                        const error = new Error('Will not override empty filters in updateInsight.')
                        captureException(error, {
                            extra: {
                                filters: JSON.stringify(insight.filters),
                                insight: JSON.stringify(insight),
                                valuesInsight: JSON.stringify(values.insight),
                            },
                        })
                        throw error
                    }

                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                        insight
                    )
                    breakpoint()
                    const updatedInsight: InsightModel = {
                        ...response,
                        result: response.result || values.insight.result,
                    }
                    callback?.(updatedInsight)

                    const removedDashboards = (values.insight.dashboards || []).filter(
                        (d) => !updatedInsight.dashboards?.includes(d)
                    )
                    dashboardsModel.actions.updateDashboardInsight(updatedInsight, removedDashboards)
                    return updatedInsight
                },
                setInsightMetadata: async ({ metadata }, breakpoint) => {
                    const editMode =
                        insightSceneLogic.isMounted() &&
                        insightSceneLogic.values.insight === values.insight &&
                        insightSceneLogic.values.insightMode === ItemMode.Edit

                    if (editMode) {
                        return { ...values.insight, ...metadata }
                    }

                    if (metadata.filters) {
                        const error = new Error(`Will not override filters in setInsightMetadata`)
                        captureException(error, {
                            extra: {
                                filters: JSON.stringify(values.insight.filters),
                                insight: JSON.stringify(values.insight),
                            },
                        })
                        throw error
                    }

                    const beforeUpdates = {}
                    for (const key of Object.keys(metadata)) {
                        beforeUpdates[key] = values.savedInsight[key]
                    }

                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                        metadata
                    )
                    breakpoint()

                    // only update the fields that we changed
                    const updatedInsight = { ...values.insight } as InsightModel
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
                                    `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                                    beforeUpdates
                                )
                                // only update the fields that we changed
                                const revertedInsight = { ...values.insight } as InsightModel
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
                } else {
                    return state
                }
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
                } else {
                    return state
                }
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
        /* filters contains the in-flight filters, might not (yet?) be the same as insight.filters */
        filters: [
            () => props.cachedInsight?.filters || ({} as Partial<FilterType>),
            {
                setFilters: (_, { filters }) => cleanFilters(filters),
                setInsight: (state, { insight: { filters }, options: { overrideFilter } }) =>
                    overrideFilter ? cleanFilters(filters || {}) : state,
                loadInsightSuccess: (state, { insight }) =>
                    Object.keys(state).length === 0 && insight.filters ? insight.filters : state,
            },
        ],
        /** The insight's state as it is in the database. */
        savedInsight: [
            () => props.cachedInsight || ({} as InsightModel),
            {
                setInsight: (state, { insight, options: { fromPersistentApi } }) =>
                    fromPersistentApi ? { ...insight, filters: cleanFilters(insight.filters || {}) } : state,
                loadInsightSuccess: (_, { insight }) => ({ ...insight, filters: cleanFilters(insight.filters || {}) }),
                updateInsightSuccess: (_, { insight }) => ({
                    ...insight,
                    filters: cleanFilters(insight.filters || {}),
                }),
            },
        ],
        insightLoading: [
            false,
            {
                setIsLoading: (_, { isLoading }) => isLoading,
                loadInsight: () => true,
                loadInsightSuccess: () => false,
                loadInsightFailure: () => false,
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
        /** filters for data that's being displayed, might not be same as `savedInsight.filters` or filters */
        loadedFilters: [(s) => [s.insight], (insight) => insight.filters],
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
            (s) => [s.insight, s.aggregationLabel, s.cohortsById, s.mathDefinitions],
            (insight, aggregationLabel, cohortsById, mathDefinitions) =>
                summarizeInsight(insight.query, insight.filters || {}, {
                    aggregationLabel,
                    cohortsById,
                    mathDefinitions,
                }).slice(0, 400),
        ],
        insightName: [(s) => [s.insight, s.derivedName], (insight, derivedName) => insight.name || derivedName],
        insightId: [(s) => [s.insight], (insight) => insight?.id || null],
        isFilterBasedInsight: [
            (s) => [s.insight],
            (insight) => Object.keys(insight.filters || {}).length > 0 && !insight.query,
        ],
        isQueryBasedInsight: [(s) => [s.insight], (insight) => !!insight.query],
        isInsightVizQuery: [(s) => [s.insight], (insight) => isInsightVizNode(insight.query)],
        canEditInsight: [
            (s) => [s.insight],
            (insight) =>
                insight.effective_privilege_level == undefined ||
                insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit,
        ],
        insightChanged: [
            (s) => [s.insight, s.savedInsight],
            (insight, savedInsight): boolean => {
                return (
                    (insight.name || '') !== (savedInsight.name || '') ||
                    (insight.description || '') !== (savedInsight.description || '') ||
                    !objectsEqual(insight.tags || [], savedInsight.tags || [])
                )
            },
        ],
        allEventNames: [
            (s) => [s.filters, actionsModel.selectors.actions],
            (filters, actions: ActionType[]) => {
                const allEvents = [
                    ...(filters.events || []).map((e) => e.id),
                    ...(filters.actions || []).flatMap((action) => getEventNamesForAction(action.id, actions)),
                ]
                // Has one "all events" event.
                if (allEvents.some((e) => e === null)) {
                    return []
                }
                // remove duplicates and empty events
                return Array.from(new Set(allEvents.filter((a): a is string => !!a)))
            },
        ],
        hiddenLegendKeys: [
            (s) => [s.filters],
            (filters) => {
                if (isFilterWithHiddenLegendKeys(filters) && filters.hidden_legend_keys) {
                    return transformLegacyHiddenLegendKeys(filters.hidden_legend_keys)
                }

                return {}
            },
        ],
        filtersKnown: [
            (s) => [s.insight],
            ({ filters }) => {
                // any real filter will have the `insight` key in it
                return 'insight' in (filters ?? {})
            },
        ],
        filterPropertiesCount: [
            (s) => [s.filters],
            (filters): number => {
                return Array.isArray(filters.properties)
                    ? filters.properties.length
                    : sum(filters.properties?.values?.map((x) => x.values.length) || [])
            },
        ],
        localFilters: [
            (s) => [s.filters],
            (filters) => {
                return toLocalFilters(filters)
            },
        ],
        intervalUnit: [(s) => [s.filters], (filters) => filters?.interval || 'day'],
        exporterResourceParams: [
            (s) => [s.filters, s.currentTeamId, s.insight],
            (
                filters: Partial<FilterType>,
                currentTeamId: number | null,
                insight: Partial<InsightModel>
            ): TriggerExportProps['export_context'] | null => {
                if (!currentTeamId) {
                    return null
                }

                const params = { ...filters }

                const filename = ['export', insight.name || insight.derived_name].join('-')

                if (insight.query) {
                    return { ...queryExportContext(insight.query, undefined, undefined, false), filename }
                } else {
                    if (isTrendsFilter(filters) || isStickinessFilter(filters) || isLifecycleFilter(filters)) {
                        return {
                            path: `api/projects/${currentTeamId}/insights/trend/?${toParams(
                                filterTrendsClientSideParams(params)
                            )}`,
                            filename,
                        }
                    } else if (isRetentionFilter(filters)) {
                        return {
                            filename,
                            path: `api/projects/${currentTeamId}/insights/retention/?${toParams(params)}`,
                        }
                    } else if (isFunnelsFilter(filters)) {
                        return {
                            filename,
                            method: 'POST',
                            path: `api/projects/${currentTeamId}/insights/funnel`,
                            body: params,
                        }
                    } else if (isPathsFilter(filters)) {
                        return {
                            filename,
                            method: 'POST',
                            path: `api/projects/${currentTeamId}/insights/path`,
                            body: params,
                        }
                    } else {
                        return null
                    }
                }
            },
        ],
        isUsingSessionAnalysis: [
            (s) => [s.filters],
            (filters: Partial<FilterType>): boolean => {
                const entities = (filters.events || []).concat(filters.actions ?? [])
                const using_session_breakdown = filters.breakdown_type === 'session'
                const using_session_math = entities.some((entity) => entity.math === 'unique_session')
                const using_session_property_math = entities.some((entity) => {
                    // Should be made more generic is we ever add more session properties
                    return entity.math_property === '$session_duration'
                })
                const using_entity_session_property_filter = entities.some((entity) => {
                    return parseProperties(entity.properties).some((property) => property.type === 'session')
                })
                const using_global_session_property_filter = parseProperties(filters.properties).some(
                    (property) => property.type === 'session'
                )
                return (
                    using_session_breakdown ||
                    using_session_math ||
                    using_session_property_math ||
                    using_entity_session_property_filter ||
                    using_global_session_property_filter
                )
            },
        ],
        showPersonsModal: [() => [(_, p) => p.query], (query?: InsightVizNode) => !query || !query.hidePersonsModal],
    }),
    listeners(({ actions, selectors, values }) => ({
        setFiltersMerge: ({ filters }) => {
            actions.setFilters({ ...values.filters, ...filters })
        },
        setFilters: async ({ filters }, _, __, previousState) => {
            const previousFilters = selectors.filters(previousState)
            if (objectsEqual(previousFilters, filters)) {
                return
            }
            const dupeFilters = { ...filters }
            const dupePrevFilters = { ...selectors.filters(previousState) }
            if ('new_entity' in dupeFilters) {
                delete (dupeFilters as any).new_entity
            }
            if ('new_entity' in dupePrevFilters) {
                delete (dupePrevFilters as any).new_entity
            }
            if (objectsEqual(dupePrevFilters, dupeFilters)) {
                return
            }

            actions.reportInsightViewed(values.insight, filters, previousFilters)
        },
        reportInsightViewedForRecentInsights: async () => {
            // Report the insight being viewed to our '/viewed' endpoint. Used for "recently viewed insights"

            // TODO: This should be merged into the same action as `reportInsightViewed`, but we can't right now
            // because there are some issues with `reportInsightViewed` not being called when the
            // insightLogic is already loaded.
            // For example, if the user navigates to an insight after viewing it on a dashboard, `reportInsightViewed`
            // will not be called. This should be fixed when we refactor insightLogic, but the logic is a bit tangled
            // right now
            if (values.insight.id) {
                return api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}/viewed`)
            }
        },
        reportInsightViewed: async ({ filters, previousFilters }, breakpoint) => {
            await breakpoint(IS_TEST_MODE ? 1 : 500) // Debounce to avoid noisy events from changing filters multiple times
            if (!values.isInDashboardContext) {
                const { fromDashboard } = router.values.hashParams
                const changedKeysObj: Record<string, any> | undefined =
                    previousFilters && extractObjectDiffKeys(previousFilters, filters)

                const insightMode =
                    insightSceneLogic.isMounted() && insightSceneLogic.values.insight === values.insight
                        ? insightSceneLogic.values.insightMode
                        : ItemMode.View

                eventUsageLogic.actions.reportInsightViewed(
                    values.insight,
                    filters || {},
                    insightMode,
                    values.isFirstLoad,
                    Boolean(fromDashboard),
                    0,
                    changedKeysObj,
                    values.isUsingSessionAnalysis
                )

                actions.setNotFirstLoad()
                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish

                eventUsageLogic.actions.reportInsightViewed(
                    values.insight,
                    filters || {},
                    insightMode,
                    values.isFirstLoad,
                    Boolean(fromDashboard),
                    10,
                    changedKeysObj,
                    values.isUsingSessionAnalysis
                )
            }
        },
        saveInsight: async ({ redirectToViewMode }) => {
            const insightNumericId =
                values.insight.id || (values.insight.short_id ? await getInsightId(values.insight.short_id) : undefined)
            const { name, description, favorited, filters, query, deleted, dashboards, tags } = values.insight
            let savedInsight: InsightModel

            try {
                // We don't want to send ALL the insight properties back to the API, so only grabbing fields that might have changed
                const insightRequest: Partial<InsightModel> = {
                    name,
                    derived_name: values.derivedName,
                    description,
                    favorited,
                    filters,
                    query: query ? query : null,
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
            const result = savedInsight.result || (query ? values.insight.result : null)
            actions.setInsight({ ...savedInsight, result: result }, { fromPersistentApi: true, overrideFilter: true })
            eventUsageLogic.actions.reportInsightSaved(filters || {}, insightNumericId === undefined)
            lemonToast.success(`Insight saved${dashboards?.length === 1 ? ' & added to dashboard' : ''}`, {
                button: {
                    label: 'View Insights list',
                    action: () => router.actions.push(urls.savedInsights()),
                },
            })

            dashboardsModel.actions.updateDashboardInsight(savedInsight)

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
        saveAsNamingSuccess: async ({ name }) => {
            const insight: InsightModel = await api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/`, {
                name,
                filters: values.filters,
                query: values.insight.query,
                saved: true,
            })
            lemonToast.info(`You're now working on a copy of ${values.insight.name ?? values.insight.derived_name}`)
            actions.setInsight(insight, { fromPersistentApi: true, overrideFilter: true })
            savedInsightsLogic.findMounted()?.actions.loadInsights() // Load insights afresh
            router.actions.push(urls.insightEdit(insight.short_id))
        },
        loadInsightSuccess: async ({ insight }) => {
            actions.reportInsightViewed(insight, insight?.filters || {})
        },
        toggleVisibility: ({ index }) => {
            const currentIsHidden = !!values.hiddenLegendKeys?.[index]
            const newFilters: Partial<TrendsFilterType> = {
                ...values.filters,
                hidden_legend_keys: {
                    ...values.hiddenLegendKeys,
                    [`${index}`]: currentIsHidden ? undefined : true,
                },
            }
            actions.setFilters(newFilters)
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

            const insight = findInsightFromMountedLogic(
                props.dashboardItemId as string | InsightShortId,
                props.dashboardId
            )
            if (insight) {
                actions.setInsight(insight, { overrideFilter: true, fromPersistentApi: true })
                if (insight?.result) {
                    actions.reportInsightViewed(insight, insight.filters || {})
                }
                return
            }

            if (!props.doNotLoad) {
                actions.loadInsight(props.dashboardItemId as InsightShortId)
            }
        },
    })),
])
