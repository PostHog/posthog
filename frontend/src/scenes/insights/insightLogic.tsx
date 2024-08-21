import { LemonDialog, LemonInput } from '@posthog/lemon-ui'
import { actions, connect, events, kea, key, listeners, LogicWrapper, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { DashboardPrivilegeLevel, FEATURE_FLAGS } from 'lib/constants'
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
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupsModel } from '~/models/groupsModel'
import { insightsModel } from '~/models/insightsModel'
import { tagsModel } from '~/models/tagsModel'
import { Node } from '~/queries/schema'
import { InsightLogicProps, InsightShortId, ItemMode, QueryBasedInsightModel, SetInsightOptions } from '~/types'

import { teamLogic } from '../teamLogic'
import { insightDataLogic } from './insightDataLogic'
import type { insightLogicType } from './insightLogicType'
import { getInsightId } from './utils'
import { insightsApi, InsightsApiOptions } from './utils/api'

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
        ],
        actions: [tagsModel, ['loadTags']],
        logic: [eventUsageLogic, dashboardsModel],
    })),

    actions({
        setInsight: (insight: Partial<QueryBasedInsightModel>, options: SetInsightOptions) => ({
            insight,
            options,
        }),
        saveAs: (redirectToViewMode?: boolean, persist?: boolean) => ({ redirectToViewMode, persist }),
        saveAsConfirmation: (name: string, redirectToViewMode = false, persist = true) => ({
            name,
            redirectToViewMode,
            persist,
        }),
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        saveInsightSuccess: true,
        saveInsightFailure: true,
        loadInsight: (shortId: InsightShortId) => ({
            shortId,
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
    }),
    loaders(({ actions, values, props }) => ({
        insight: [
            props.cachedInsight ?? createEmptyInsight(props.dashboardItemId || 'new'),
            {
                loadInsight: async ({ shortId }, breakpoint) => {
                    await breakpoint(100)
                    const insight = await insightsApi.getByShortId(shortId, undefined, 'async')

                    if (!insight) {
                        throw new Error(`Insight with shortId ${shortId} not found`)
                    }

                    return insight
                },
                updateInsight: async ({ insightUpdate, callback }, breakpoint) => {
                    if (!Object.entries(insightUpdate).length) {
                        return values.insight
                    }

                    const response = await insightsApi.update(values.insight.id as number, insightUpdate, {
                        writeAsQuery: values.queryBasedInsightSaving,
                    })
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
                    return updatedInsight
                },
                setInsightMetadata: async ({ metadataUpdate }, breakpoint) => {
                    const editMode =
                        insightSceneLogic.isMounted() &&
                        insightSceneLogic.values.insight === values.insight &&
                        insightSceneLogic.values.insightMode === ItemMode.Edit

                    if (editMode) {
                        return { ...values.insight, ...metadataUpdate }
                    }

                    const beforeUpdates = {}
                    for (const key of Object.keys(metadataUpdate)) {
                        beforeUpdates[key] = values.savedInsight[key]
                    }

                    const response = await insightsApi.update(values.insight.id as number, metadataUpdate, {
                        writeAsQuery: values.queryBasedInsightSaving,
                    })
                    breakpoint()

                    savedInsightsLogic.findMounted()?.actions.loadInsights()
                    dashboardsModel.actions.updateDashboardInsight(response)
                    actions.loadTags()

                    lemonToast.success(`Updated insight`, {
                        button: {
                            label: 'Undo',
                            dataAttr: 'edit-insight-undo',
                            action: async () => {
                                const response = await insightsApi.update(values.insight.id as number, beforeUpdates, {
                                    writeAsQuery: values.queryBasedInsightSaving,
                                })
                                savedInsightsLogic.findMounted()?.actions.loadInsights()
                                dashboardsModel.actions.updateDashboardInsight(response)
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
            setInsight: (_state, { insight }) => ({
                ...insight,
            }),
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
    })),
    selectors({
        query: [
            (s) => [(state) => insightDataLogic.findMounted(s.insightProps(state))?.values.query || null],
            (node): Node | null => node,
        ],
        queryBasedInsightSaving: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.QUERY_BASED_INSIGHTS_SAVING],
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
        showPersonsModal: [() => [(s) => s.query], (query) => !query || !query.hidePersonsModal],
    }),
    listeners(({ actions, values }) => ({
        saveInsight: async ({ redirectToViewMode }) => {
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

                const options: InsightsApiOptions = {
                    writeAsQuery: values.queryBasedInsightSaving,
                }
                savedInsight = insightNumericId
                    ? await insightsApi.update(insightNumericId, insightRequest, options)
                    : await insightsApi.create(insightRequest, options)
                savedInsightsLogic.findMounted()?.actions.loadInsights() // Load insights afresh
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
        saveAs: async ({ redirectToViewMode, persist }) => {
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
                onSubmit: async ({ name }) => actions.saveAsConfirmation(name, redirectToViewMode, persist),
            })
        },
        saveAsConfirmation: async ({ name, redirectToViewMode, persist }) => {
            const insight = await insightsApi.create(
                {
                    name,
                    query: values.query,
                    saved: true,
                },
                {
                    writeAsQuery: values.queryBasedInsightSaving,
                }
            )
            lemonToast.info(
                `You're now working on a copy of ${values.insight.name || values.insight.derived_name || name}`
            )
            persist && actions.setInsight(insight, { fromPersistentApi: true, overrideQuery: true })
            savedInsightsLogic.findMounted()?.actions.loadInsights() // Load insights afresh

            if (redirectToViewMode) {
                router.actions.push(urls.insightView(insight.short_id))
            } else {
                router.actions.push(urls.insightEdit(insight.short_id))
            }
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
