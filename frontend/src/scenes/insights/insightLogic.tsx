import { LemonDialog, LemonInput } from '@posthog/lemon-ui'
import { actions, connect, events, kea, key, listeners, LogicWrapper, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { accessLevelSatisfied } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { summarizeInsight } from 'scenes/insights/summarizeInsight'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { activationLogic, ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { getLastNewFolder, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupsModel } from '~/models/groupsModel'
import { insightsModel } from '~/models/insightsModel'
import { tagsModel } from '~/models/tagsModel'
import { DashboardFilter, HogQLVariable, Node } from '~/queries/schema/schema-general'
import { isValidQueryForExperiment } from '~/queries/utils'
import {
    AccessControlResourceType,
    InsightLogicProps,
    InsightShortId,
    ItemMode,
    QueryBasedInsightModel,
    SetInsightOptions,
} from '~/types'

import { teamLogic } from '../teamLogic'
import { insightDataLogic } from './insightDataLogic'
import type { insightLogicType } from './insightLogicType'
import { getInsightId } from './utils'
import { insightsApi } from './utils/api'

export const UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES = 3

export const createEmptyInsight = (
    shortId: InsightShortId | `new-${string}` | 'new'
): Partial<QueryBasedInsightModel> => ({
    short_id: shortId !== 'new' && !shortId.startsWith('new-') ? (shortId as InsightShortId) : undefined,
    name: '',
    description: '',
    tags: [],
    result: null,
})

export const insightLogic: LogicWrapper<insightLogicType> = kea<insightLogicType>([
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
            sceneLogic,
            ['activeScene'],
        ],
        actions: [tagsModel, ['loadTags']],
        logic: [eventUsageLogic, dashboardsModel],
    })),

    actions({
        setInsight: (insight: Partial<QueryBasedInsightModel>, options: SetInsightOptions) => ({
            insight,
            options,
        }),
        saveAs: (redirectToViewMode?: boolean, persist?: boolean, folder?: string | null) => ({
            redirectToViewMode,
            persist,
            folder,
        }),
        saveAsConfirmation: (name: string, redirectToViewMode = false, persist = true, folder?: string | null) => ({
            name,
            redirectToViewMode,
            persist,
            folder,
        }),
        saveInsight: (redirectToViewMode: boolean = true, folder: string | null = null) => ({
            redirectToViewMode,
            folder,
        }),
        saveInsightSuccess: true,
        saveInsightFailure: true,
        loadInsight: (
            shortId: InsightShortId,
            filtersOverride?: DashboardFilter | null,
            variablesOverride?: Record<string, HogQLVariable> | null
        ) => ({
            shortId,
            filtersOverride,
            variablesOverride,
        }),
        updateInsight: (insightUpdate: Partial<QueryBasedInsightModel>, callback?: () => void) => ({
            insightUpdate,
            callback,
        }),
        setInsightMetadata: (
            metadataUpdate: Partial<Pick<QueryBasedInsightModel, 'name' | 'description' | 'tags' | 'favorited'>>
        ) => ({
            metadataUpdate,
        }),
        highlightSeries: (seriesIndex: number | null) => ({ seriesIndex }),
        setAccessDeniedToInsight: true,
        handleInsightSuggested: (suggestedInsight: Node | null) => ({ suggestedInsight }),
        onRejectSuggestedInsight: true,
        onReapplySuggestedInsight: true,
        setPreviousQuery: (previousQuery: Node | null) => ({ previousQuery }),
        setSuggestedQuery: (suggestedQuery: Node | null) => ({ suggestedQuery }),
    }),
    loaders(({ actions, values, props }) => ({
        insight: [
            props.cachedInsight ?? createEmptyInsight(props.dashboardItemId || 'new'),
            {
                loadInsight: async ({ shortId, filtersOverride, variablesOverride }, breakpoint) => {
                    await breakpoint(100)
                    try {
                        const insight = await insightsApi.getByShortId(
                            shortId,
                            undefined,
                            'async',
                            filtersOverride,
                            variablesOverride
                        )

                        if (!insight) {
                            throw new Error(`Insight with shortId ${shortId} not found`)
                        }

                        return insight
                    } catch (error: any) {
                        if (error.status === 403 && error.code === 'permission_denied') {
                            actions.setAccessDeniedToInsight()
                        }
                        throw error
                    }
                },
                updateInsight: async ({ insightUpdate, callback }, breakpoint) => {
                    if (!Object.entries(insightUpdate).length) {
                        return values.insight
                    }
                    const response = await insightsApi.update(values.insight.id as number, insightUpdate)
                    breakpoint()
                    const updatedInsight: QueryBasedInsightModel = {
                        ...response,
                        result: response.result || values.insight.result,
                    }
                    callback?.()

                    const removedDashboards = (values.insight.dashboards || []).filter(
                        (d) => !updatedInsight.dashboards?.includes(d)
                    )
                    dashboardsModel.actions.updateDashboardInsight(updatedInsight, removedDashboards)
                    values.insight.short_id && refreshTreeItem('insight', String(values.insight.short_id))
                    return updatedInsight
                },
                setInsightMetadata: async ({ metadataUpdate }, breakpoint) => {
                    // new insight
                    if (values.insight.short_id == null) {
                        return { ...values.insight, ...metadataUpdate }
                    }

                    const beforeUpdates: Record<string, any> = {}
                    for (const key of Object.keys(metadataUpdate)) {
                        beforeUpdates[key] = values.savedInsight[key]
                    }

                    const response = await insightsApi.update(values.insight.id as number, metadataUpdate)
                    await breakpoint(300)

                    savedInsightsLogic.findMounted()?.actions.loadInsights()
                    dashboardsModel.findMounted()?.actions.updateDashboardInsight(response)
                    actions.loadTags()

                    refreshTreeItem('insight', values.insight.short_id)
                    lemonToast.success(`Updated insight`, {
                        button: {
                            label: 'Undo',
                            dataAttr: 'edit-insight-undo',
                            action: async () => {
                                const response = await insightsApi.update(values.insight.id as number, beforeUpdates)
                                savedInsightsLogic.findMounted()?.actions.loadInsights()
                                dashboardsModel.findMounted()?.actions.updateDashboardInsight(response)
                                actions.setInsight(response, { overrideQuery: false, fromPersistentApi: true })
                                lemonToast.success('Insight change reverted')
                            },
                        },
                    })

                    return response
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
                          query: null,
                      },
            setInsight: (state, { insight }) => {
                // Preserve the user-edited name when loading new data
                if (!insight.name && state.name) {
                    return {
                        ...insight,
                        name: state.name,
                    }
                }
                return { ...insight }
            },
            setInsightMetadata: (state, { metadataUpdate }) => ({ ...state, ...metadataUpdate }),
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
        accessDeniedToInsight: [false, { setAccessDeniedToInsight: () => true }],
        /** The insight's state as it is in the database. */
        savedInsight: [
            () => props.cachedInsight || ({} as Partial<QueryBasedInsightModel>),
            {
                setInsight: (state, { insight, options: { fromPersistentApi } }) =>
                    fromPersistentApi ? { ...insight, query: insight.query || null } : state,
                loadInsightSuccess: (_, { insight }) => ({
                    ...insight,
                    query: insight.query || null,
                }),
                updateInsightSuccess: (_, { insight }) => ({
                    ...insight,
                    query: insight.query || null,
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
        previousQuery: [
            null as Node | null,
            {
                setPreviousQuery: (_, { previousQuery }) => previousQuery,
            },
        ],
        suggestedQuery: [
            null as Node | null,
            {
                setSuggestedQuery: (_, { suggestedQuery }) => suggestedQuery,
            },
        ],
        hasRejected: [
            false,
            {
                onRejectSuggestedInsight: () => true,
                onReapplySuggestedInsight: () => false,
                handleInsightSuggested: () => false,
            },
        ],
    })),
    selectors({
        query: [
            (s) => [(state) => insightDataLogic.findMounted(s.insightProps(state))?.values.query || null],
            (node): Node | null => node,
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
        isInViewMode: [() => [router.selectors.location], ({ pathname }) => /\/insights\/[a-zA-Z0-9]+$/.test(pathname)],
        derivedName: [
            (s) => [s.query, s.aggregationLabel, s.cohortsById, s.mathDefinitions],
            (query, aggregationLabel, cohortsById, mathDefinitions) =>
                summarizeInsight(query, {
                    aggregationLabel,
                    cohortsById,
                    mathDefinitions,
                }).slice(0, 400),
        ],
        insightName: [(s) => [s.insight, s.derivedName], (insight, derivedName) => insight.name || derivedName],
        insightId: [(s) => [s.insight], (insight) => insight?.id || null],
        canEditInsight: [
            (s) => [s.insight],
            (insight) => {
                return insight.user_access_level
                    ? accessLevelSatisfied(AccessControlResourceType.Insight, insight.user_access_level, 'editor')
                    : true
            },
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
        showPersonsModal: [
            (s) => [s.query, s.insightProps, s.featureFlags],
            (query: Record<string, any>, insightProps: InsightLogicProps): boolean => {
                const theQuery = query || insightProps?.query
                return !theQuery || !theQuery.hidePersonsModal
            },
        ],
        supportsCreatingExperiment: [
            (s) => [s.insight, s.activeScene],
            (insight: QueryBasedInsightModel, activeScene: Scene) =>
                insight?.query &&
                isValidQueryForExperiment(insight.query) &&
                ![
                    Scene.Experiment,
                    Scene.Experiments,
                    Scene.ExperimentsSharedMetric,
                    Scene.ExperimentsSharedMetrics,
                ].includes(activeScene),
        ],
        isUsingPathsV1: [(s) => [s.featureFlags], (featureFlags) => !featureFlags[FEATURE_FLAGS.PATHS_V2]],
        isUsingPathsV2: [(s) => [s.featureFlags], (featureFlags) => featureFlags[FEATURE_FLAGS.PATHS_V2]],
    }),
    listeners(({ actions, values }) => ({
        saveInsight: async ({ redirectToViewMode, folder }) => {
            const insightNumericId =
                values.insight.id || (values.insight.short_id ? await getInsightId(values.insight.short_id) : undefined)
            const { name, description, favorited, deleted, dashboards, tags } = values.insight

            let savedInsight: QueryBasedInsightModel

            try {
                // We don't want to send ALL the insight properties back to the API, so only grabbing fields that might have changed
                const insightRequest: Partial<QueryBasedInsightModel> = {
                    name,
                    derived_name: values.derivedName,
                    description,
                    favorited,
                    query: values.query,
                    deleted,
                    saved: true,
                    dashboards,
                    tags,
                }

                savedInsight = insightNumericId
                    ? await insightsApi.update(insightNumericId, insightRequest)
                    : await insightsApi.create({
                          ...insightRequest,
                          _create_in_folder: folder ?? getLastNewFolder(),
                      })
                savedInsightsLogic.findMounted()?.actions.loadInsights() // Load insights afresh
                // remove draft query from local storage
                localStorage.removeItem(`draft-query-${values.currentTeamId}`)
                actions.saveInsightSuccess()
            } catch (e) {
                actions.saveInsightFailure()
                throw e
            }

            // the backend can't return the result for a query based insight,
            // and so we shouldn't copy the result from `values.insight` as it might be stale
            const result = savedInsight.result || (values.query ? values.insight.result : null)
            actions.setInsight({ ...savedInsight, result: result }, { fromPersistentApi: true, overrideQuery: true })
            eventUsageLogic.actions.reportInsightSaved(values.query, insightNumericId === undefined)
            lemonToast.success(`Insight saved${dashboards?.length === 1 ? ' & added to dashboard' : ''}`, {
                button: {
                    label: 'View Insights list',
                    action: () => router.actions.push(urls.savedInsights()),
                },
            })

            dashboardsModel.findMounted()?.actions.updateDashboardInsight(savedInsight)

            // reload dashboards with updated insight
            // since filters on dashboard might be different from filters on insight
            // we need to trigger dashboard reload to pick up results for updated insight
            savedInsight.dashboard_tiles?.forEach(({ dashboard_id }) =>
                dashboardLogic.findMounted({ id: dashboard_id })?.actions.loadDashboard({
                    action: 'update',
                    manualDashboardRefresh: false,
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
        saveInsightSuccess: async () => {
            activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.CreateFirstInsight)
        },
        saveAs: async ({ redirectToViewMode, persist, folder }) => {
            LemonDialog.openForm({
                title: 'Save as new insight',
                initialValues: {
                    name:
                        values.insight.name || values.insight.derived_name
                            ? `${values.insight.name || values.insight.derived_name} (copy)`
                            : '',
                },
                content: (
                    <LemonField name="name">
                        <LemonInput data-attr="insight-name" placeholder="Please enter the new name" autoFocus />
                    </LemonField>
                ),
                errors: {
                    name: (name) => (!name ? 'You must enter a name' : undefined),
                },
                onSubmit: async ({ name }) => actions.saveAsConfirmation(name, redirectToViewMode, persist, folder),
            })
        },
        saveAsConfirmation: async ({ name, redirectToViewMode, persist, folder }) => {
            const insight = await insightsApi.create({
                name,
                query: values.query,
                saved: true,
                _create_in_folder: folder ?? getLastNewFolder(),
            })

            if (router.values.location.pathname.includes(urls.sqlEditor())) {
                lemonToast.info(`You're now viewing ${values.insight.name || values.insight.derived_name || name}`)
            } else {
                lemonToast.info(
                    `You're now working on a copy of ${values.insight.name || values.insight.derived_name || name}`
                )
            }

            persist && actions.setInsight(insight, { fromPersistentApi: true, overrideQuery: true })
            savedInsightsLogic.findMounted()?.actions.loadInsights() // Load insights afresh

            if (redirectToViewMode) {
                router.actions.push(urls.insightView(insight.short_id))
            } else {
                router.actions.push(urls.insightEdit(insight.short_id))
            }
        },
        onRejectSuggestedInsight: () => {
            if (values.previousQuery) {
                const insightDataLogicInstance = insightDataLogic.findMounted(values.insightProps)
                if (insightDataLogicInstance) {
                    insightDataLogicInstance.actions.setQuery(values.previousQuery)
                }
            }
        },
        handleInsightSuggested: ({ suggestedInsight }) => {
            if (suggestedInsight) {
                const insightDataLogicInstance = insightDataLogic.findMounted(values.insightProps)
                if (insightDataLogicInstance) {
                    const currentQuery = insightDataLogicInstance.values.query
                    actions.setPreviousQuery(currentQuery)
                    actions.setSuggestedQuery(suggestedInsight)
                }
            }
        },
        onReapplySuggestedInsight: () => {
            // Reapply the Max AI suggestion
            if (values.suggestedQuery) {
                const insightDataLogicInstance = insightDataLogic.findMounted(values.insightProps)
                if (insightDataLogicInstance) {
                    insightDataLogicInstance.actions.setQuery(values.suggestedQuery)
                }
            }
        },
    })),
    events(({ props, actions }) => ({
        afterMount: () => {
            if (!props.dashboardItemId || props.dashboardItemId === 'new' || props.dashboardItemId.startsWith('new-')) {
                return
            }

            if (!props.doNotLoad && !props.cachedInsight) {
                actions.loadInsight(
                    props.dashboardItemId as InsightShortId,
                    props.filtersOverride,
                    props.variablesOverride
                )
            }
        },
    })),
])
