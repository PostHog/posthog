import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { IconDashboard, IconGraph } from '@posthog/icons'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { DashboardLoadAction, RefreshStatus, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { ActionType, DashboardType, EventDefinition, InsightShortId, QueryBasedInsightModel } from '~/types'

import {
    REVENUE_ANALYTICS_QUERY_TO_NAME,
    REVENUE_ANALYTICS_QUERY_TO_SHORT_ID,
    RevenueAnalyticsQuery,
    revenueAnalyticsLogic,
} from 'products/revenue_analytics/frontend/revenueAnalyticsLogic'

import type { maxContextLogicType } from './maxContextLogicType'
import {
    InsightWithQuery,
    MaxActionContext,
    MaxContextInput,
    MaxContextItem,
    MaxContextTaxonomicFilterOption,
    MaxContextType,
    MaxDashboardContext,
    MaxEventContext,
    MaxInsightContext,
    MaxUIContext,
} from './maxTypes'
import {
    actionToMaxContextPayload,
    dashboardToMaxContext,
    eventToMaxContextPayload,
    insightToMaxContext,
} from './utils'

// Type definitions for better reusability
export type TaxonomicItem =
    | DashboardType
    | QueryBasedInsightModel
    | EventDefinition
    | ActionType
    | MaxContextTaxonomicFilterOption

export type DashboardItemInfo = { id: number; preloaded: DashboardType<QueryBasedInsightModel> | null }
export type InsightItemInfo = { id: InsightShortId; preloaded: QueryBasedInsightModel | null }

type EntityWithIdAndType = { id: string | number; type: string }

const addOrUpdateEntity = <TContext extends EntityWithIdAndType>(state: TContext[], entity: TContext): TContext[] =>
    state.filter((item) => item.id !== entity.id).concat(entity)

const removeEntity = <TContext extends EntityWithIdAndType>(state: TContext[], id: string | number): TContext[] =>
    state.filter((item) => item.id !== id)

export type LoadedEntitiesMap = { dashboard: number[]; insight: string[] }

export const maxContextLogic = kea<maxContextLogicType>([
    path(['scenes', 'max', 'maxContextLogic']),
    connect(() => ({
        values: [sceneLogic, ['activeSceneId', 'activeSceneLogic', 'activeLoadedScene']],
        actions: [router, ['locationChanged']],
    })),
    actions({
        addOrUpdateContextInsight: (
            data: InsightWithQuery,
            filtersOverride?: DashboardFilter,
            variablesOverride?: Record<string, HogQLVariable>
        ) => ({ data, filtersOverride, variablesOverride }),
        addOrUpdateContextDashboard: (data: DashboardType<QueryBasedInsightModel>) => ({ data }),
        addOrUpdateContextEvent: (data: EventDefinition) => ({ data }),
        addOrUpdateContextAction: (data: ActionType) => ({ data }),
        removeContextInsight: (id: string | number) => ({ id }),
        removeContextDashboard: (id: string | number) => ({ id }),
        removeContextEvent: (id: string | number) => ({ id }),
        removeContextAction: (id: string | number) => ({ id }),
        loadAndProcessDashboard: (data: DashboardItemInfo) => ({ data }),
        loadAndProcessInsight: (
            data: InsightItemInfo,
            filtersOverride?: DashboardFilter,
            variablesOverride?: Record<string, HogQLVariable>,
            revenueAnalyticsQuery?: RevenueAnalyticsQuery
        ) => ({ data, filtersOverride, variablesOverride, revenueAnalyticsQuery }),
        setSelectedContextOption: (value: string) => ({ value }),
        handleTaxonomicFilterChange: (
            value: string | number,
            groupType: TaxonomicFilterGroupType,
            item: TaxonomicItem
        ) => ({ value, groupType, item }),
        resetContext: true,
    }),
    reducers({
        loadedEntities: [
            { dashboard: [], insight: [] } as LoadedEntitiesMap,
            {
                loadAndProcessInsight: (state: LoadedEntitiesMap, { data }: { data: InsightItemInfo }) => ({
                    ...state,
                    insight: [...state.insight, data.id],
                }),
                loadAndProcessDashboard: (state: LoadedEntitiesMap, { data }: { data: DashboardItemInfo }) => ({
                    ...state,
                    dashboard: [...state.dashboard, data.id],
                }),
            },
        ],
        contextInsights: [
            [] as MaxInsightContext[],
            {
                addOrUpdateContextInsight: (state: MaxInsightContext[], { data, filtersOverride, variablesOverride }) =>
                    addOrUpdateEntity(state, insightToMaxContext(data, filtersOverride, variablesOverride)),
                removeContextInsight: (state: MaxInsightContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                resetContext: () => [],
            },
        ],
        contextDashboards: [
            [] as MaxDashboardContext[],
            {
                addOrUpdateContextDashboard: (
                    state: MaxDashboardContext[],
                    { data }: { data: DashboardType<QueryBasedInsightModel> }
                ) => addOrUpdateEntity(state, dashboardToMaxContext(data)),
                removeContextDashboard: (state: MaxDashboardContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                resetContext: () => [],
            },
        ],
        contextEvents: [
            [] as MaxEventContext[],
            {
                addOrUpdateContextEvent: (state: MaxEventContext[], { data }: { data: EventDefinition }) =>
                    addOrUpdateEntity(state, eventToMaxContextPayload(data)),
                removeContextEvent: (state: MaxEventContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                resetContext: () => [],
            },
        ],
        contextActions: [
            [] as MaxActionContext[],
            {
                addOrUpdateContextAction: (state: MaxActionContext[], { data }: { data: ActionType }) =>
                    addOrUpdateEntity(state, actionToMaxContextPayload(data)),
                removeContextAction: (state: MaxActionContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                resetContext: () => [],
            },
        ],
    }),
    listeners(({ actions, cache }) => ({
        locationChanged: () => {
            // Don't reset context if the only change is the side panel opening/closing
            const currentLocation = router.values.location
            const currentHashParams = router.values.hashParams || {}
            const currentSearchParams = router.values.searchParams || {}
            const previousLocation = cache.previousLocation

            cache.previousLocation = {
                location: currentLocation,
                hashParams: currentHashParams,
                searchParams: currentSearchParams,
            }

            if (!previousLocation) {
                return
            }

            const shouldResetContext = (): void => {
                actions.resetContext()
            }

            // Always reset context if pathname changed
            if (currentLocation?.pathname !== previousLocation.location?.pathname) {
                shouldResetContext()
                return
            }

            // Check if search params changed (excluding 'chat' parameter)
            const currentSearchParamsWithoutChat = { ...currentSearchParams }
            delete currentSearchParamsWithoutChat.chat
            const previousSearchParamsWithoutChat = { ...previousLocation.searchParams }
            delete previousSearchParamsWithoutChat.chat

            if (!objectsEqual(currentSearchParamsWithoutChat, previousSearchParamsWithoutChat)) {
                shouldResetContext()
                return
            }

            // Check if only panel parameter changed in hash params
            const currentNonPanelKeys = Object.keys(currentHashParams).filter((k) => k !== 'panel')
            const previousNonPanelKeys = Object.keys(previousLocation.hashParams || {}).filter((k) => k !== 'panel')

            // Check if non-panel keys are the same
            const sameKeys =
                currentNonPanelKeys.length === previousNonPanelKeys.length &&
                currentNonPanelKeys.every(
                    (key) =>
                        previousNonPanelKeys.includes(key) &&
                        currentHashParams[key] === (previousLocation.hashParams || {})[key]
                )

            if (!sameKeys) {
                shouldResetContext()
            }
        },
        loadAndProcessDashboard: async ({ data }: { data: DashboardItemInfo }, breakpoint) => {
            let dashboard = data.preloaded

            if (!dashboard || !dashboard.tiles) {
                const dashboardLogicInstance = dashboardLogic.build({ id: data.id })
                dashboardLogicInstance.mount()

                try {
                    dashboardLogicInstance.actions.loadDashboard({ action: DashboardLoadAction.InitialLoad })

                    await breakpoint(50)
                    while (!dashboardLogicInstance.values.dashboard) {
                        await breakpoint(50)
                    }

                    dashboard = dashboardLogicInstance.values.dashboard

                    // Wait for dashboard items to refresh for cached insights
                    while (
                        Object.values(dashboardLogicInstance.values.refreshStatus).some(
                            (status: RefreshStatus) => status.loading
                        )
                    ) {
                        await breakpoint(50)
                    }
                } finally {
                    dashboardLogicInstance.unmount()
                }
            }

            if (dashboard) {
                actions.addOrUpdateContextDashboard(dashboard)
            }
        },
        loadAndProcessInsight: async (
            { data, filtersOverride, variablesOverride, revenueAnalyticsQuery },
            breakpoint
        ) => {
            let insight = data.preloaded

            if (!insight || !insight.query) {
                // Decide between revenue analytics query and querying the insight logic
                if (revenueAnalyticsQuery) {
                    const logic = revenueAnalyticsLogic.findMounted()!
                    const query = logic.values.queries[revenueAnalyticsQuery]
                    insight = {
                        id: revenueAnalyticsQuery,
                        short_id: REVENUE_ANALYTICS_QUERY_TO_SHORT_ID[revenueAnalyticsQuery],
                        name: REVENUE_ANALYTICS_QUERY_TO_NAME[revenueAnalyticsQuery],
                        query,
                    } as QueryBasedInsightModel
                } else {
                    const insightLogicInstance = insightLogic.build({
                        dashboardItemId: undefined,
                        filtersOverride,
                        variablesOverride,
                    })
                    insightLogicInstance.mount()

                    try {
                        insightLogicInstance.actions.loadInsight(data.id)

                        await breakpoint(50)
                        while (!insightLogicInstance.values.insight.query) {
                            await breakpoint(50)
                        }

                        insight = insightLogicInstance.values.insight as QueryBasedInsightModel
                    } finally {
                        insightLogicInstance.unmount()
                    }
                }
            }

            if (insight) {
                actions.addOrUpdateContextInsight(insight, filtersOverride, variablesOverride)
            }
        },
        handleTaxonomicFilterChange: async ({
            groupType,
            item,
        }: {
            groupType: TaxonomicFilterGroupType
            item: TaxonomicItem
        }) => {
            try {
                if (groupType === TaxonomicFilterGroupType.Events) {
                    actions.addOrUpdateContextEvent(item as EventDefinition)
                    return
                } else if (groupType === TaxonomicFilterGroupType.Actions) {
                    actions.addOrUpdateContextAction(item as ActionType)
                    return
                }

                // Parse item information based on selection type
                const itemInfo = (() => {
                    // Handle MaxAI context with string values like "insight_123" or "dashboard_456"
                    if (groupType === TaxonomicFilterGroupType.MaxAIContext) {
                        const _item = item as MaxContextTaxonomicFilterOption
                        if (_item.type === MaxContextType.INSIGHT) {
                            return {
                                type: MaxContextType.INSIGHT,
                                id: _item.value,
                                preloaded: null,
                            }
                        }
                        if (_item.type === MaxContextType.DASHBOARD) {
                            return isNaN(_item.value as number)
                                ? null
                                : {
                                      type: MaxContextType.DASHBOARD,
                                      id: _item.value,
                                      preloaded: null,
                                  }
                        }
                    }

                    // Handle direct selections
                    if (groupType === TaxonomicFilterGroupType.Dashboards) {
                        const dashboard = item as DashboardType
                        return {
                            type: MaxContextType.DASHBOARD,
                            id: dashboard.id,
                            preloaded: dashboard as DashboardType<QueryBasedInsightModel>,
                        }
                    }

                    if (groupType === TaxonomicFilterGroupType.Insights) {
                        const insight = item as QueryBasedInsightModel
                        return {
                            type: MaxContextType.INSIGHT,
                            id: insight.short_id,
                            preloaded: insight,
                        }
                    }

                    return null
                })()

                if (!itemInfo) {
                    return
                }

                // Handle dashboard selection
                if (itemInfo.type === MaxContextType.DASHBOARD) {
                    actions.loadAndProcessDashboard({
                        id: itemInfo.id as number,
                        preloaded: itemInfo.preloaded as DashboardType<QueryBasedInsightModel> | null,
                    })
                }

                // Handle insight selection
                if (itemInfo.type === MaxContextType.INSIGHT) {
                    let filtersOverride: DashboardFilter | undefined = undefined
                    let variablesOverride: Record<string, HogQLVariable> | undefined = undefined
                    let revenueAnalyticsQuery: RevenueAnalyticsQuery | undefined = undefined

                    // This is an "on this page" insight selection. Look for and add possible applied filters.
                    if (groupType === TaxonomicFilterGroupType.MaxAIContext) {
                        // The revenue analytics insights have some fixed short ids that don't overlap with the insight short ids
                        // Let's check them first, and then fallback to looking for an insight logic
                        const revenueAnalyticsShortIds = Object.values(REVENUE_ANALYTICS_QUERY_TO_SHORT_ID)
                        if (revenueAnalyticsShortIds.includes(itemInfo.id as InsightShortId)) {
                            revenueAnalyticsQuery = Object.entries(REVENUE_ANALYTICS_QUERY_TO_SHORT_ID).find(
                                ([_, shortId]) => shortId === itemInfo.id
                            )?.[0] as RevenueAnalyticsQuery | undefined
                        } else {
                            const logic = insightSceneLogic
                                .findAllMounted()
                                .find((l) => l.values.insightId === itemInfo.id)
                            if (logic) {
                                filtersOverride = logic.values.filtersOverride ?? undefined
                                variablesOverride = logic.values.variablesOverride ?? undefined
                            }
                        }
                    }

                    actions.loadAndProcessInsight(
                        {
                            id: itemInfo.id as InsightShortId,
                            preloaded: itemInfo.preloaded as QueryBasedInsightModel | null,
                        },
                        filtersOverride,
                        variablesOverride,
                        revenueAnalyticsQuery
                    )
                }
            } catch (error) {
                console.error('Error handling taxonomic filter change:', error)
            }
        },
    })),
    selectors({
        // Automatically collect context from active scene logic
        // This selector checks if the current scene logic has a 'maxContext' selector
        // and if so, calls it to get context items for MaxAI
        rawSceneContext: [
            () => [
                // Pass scene selector through to get automatic updates when scene changes
                (state): MaxContextInput[] => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, {})

                    if (activeSceneLogic && 'maxContext' in activeSceneLogic.selectors) {
                        try {
                            const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, {})
                            return activeSceneLogic.selectors.maxContext(
                                state,
                                activeLoadedScene?.paramsToProps?.(activeLoadedScene?.sceneParams) || {}
                            )
                        } catch {
                            // If the maxContext selector fails, return empty array
                        }
                    }
                    return []
                },
            ],
            (context: MaxContextItem[]): MaxContextItem[] => context,
            { equalityCheck: objectsEqual },
        ],
        sceneContext: [
            (s: any) => [s.rawSceneContext],
            (rawSceneContext: MaxContextInput[]): MaxContextItem[] => {
                return rawSceneContext
                    .map((item): MaxContextItem | null => {
                        switch (item.type) {
                            case MaxContextType.INSIGHT:
                                return insightToMaxContext(item.data, item.filtersOverride, item.variablesOverride)
                            case MaxContextType.DASHBOARD:
                                return dashboardToMaxContext(item.data)
                            case MaxContextType.EVENT:
                                return eventToMaxContextPayload(item.data)
                            case MaxContextType.ACTION:
                                return actionToMaxContextPayload(item.data)
                            default:
                                return null
                        }
                    })
                    .filter((item): item is MaxContextItem => item !== null)
            },
        ],
        contextOptions: [
            (s: any) => [s.sceneContext],
            (sceneContext: MaxContextItem[]): MaxContextTaxonomicFilterOption[] => {
                const options: MaxContextTaxonomicFilterOption[] = []

                sceneContext.forEach((item) => {
                    if (item.type == MaxContextType.INSIGHT) {
                        options.push({
                            id: item.id.toString(),
                            name: item.name || `Insight ${item.id}`,
                            value: item.id,
                            type: MaxContextType.INSIGHT,
                            icon: IconGraph,
                        })
                    } else if (item.type == MaxContextType.DASHBOARD) {
                        options.push({
                            id: item.id.toString(),
                            name: item.name || `Dashboard ${item.id}`,
                            value: item.id,
                            type: MaxContextType.DASHBOARD,
                            icon: IconDashboard,
                        })
                        item.insights.forEach((insight) => {
                            options.push({
                                id: insight.id.toString(),
                                name: insight.name || `Insight ${insight.id}`,
                                value: insight.id,
                                type: MaxContextType.INSIGHT,
                                icon: IconGraph,
                            })
                        })
                    }
                })

                return options
            },
        ],
        mainTaxonomicGroupType: [
            (s: any) => [s.contextOptions],
            (contextOptions: MaxContextTaxonomicFilterOption[]): TaxonomicFilterGroupType => {
                return contextOptions.length > 0
                    ? TaxonomicFilterGroupType.MaxAIContext
                    : TaxonomicFilterGroupType.Events
            },
        ],
        taxonomicGroupTypes: [
            (s: any) => [s.contextOptions],
            (contextOptions: MaxContextTaxonomicFilterOption[]): TaxonomicFilterGroupType[] => {
                const groupTypes: TaxonomicFilterGroupType[] = []
                if (contextOptions.length > 0) {
                    groupTypes.push(TaxonomicFilterGroupType.MaxAIContext)
                }
                groupTypes.push(
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.Insights,
                    TaxonomicFilterGroupType.Dashboards
                )
                return groupTypes
            },
        ],
        compiledContext: [
            (s: any) => [s.hasData, s.contextInsights, s.contextDashboards, s.contextEvents, s.contextActions],
            (
                hasData: boolean,
                contextInsights: MaxInsightContext[],
                contextDashboards: MaxDashboardContext[],
                contextEvents: MaxEventContext[],
                contextActions: MaxActionContext[]
            ): MaxUIContext | null => {
                const context: MaxUIContext = {}

                // Add context dashboards (combine manual context + scene context)
                if (contextDashboards.length > 0) {
                    context.dashboards = contextDashboards
                }

                // Add insights, filtering out those already in dashboards
                // Combine manual context, scene context, and active insights
                const allInsights = contextInsights

                if (allInsights.length > 0) {
                    // Get all insight IDs from dashboards to filter out duplicates
                    const dashboardInsightIds = new Set(
                        (context.dashboards || []).flatMap((dashboard) =>
                            dashboard.insights.map((insight) => insight.id)
                        )
                    )

                    // Filter out insights that are already included in dashboards
                    context.insights = allInsights.filter((insight) => !dashboardInsightIds.has(insight.id))
                    if (context.insights.length === 0) {
                        delete context.insights
                    }
                }

                // Deduplicate dashboards by ID
                if (context.dashboards) {
                    const uniqueDashboards = new Map()
                    context.dashboards.forEach((dashboard) => {
                        uniqueDashboards.set(dashboard.id, dashboard)
                    })
                    context.dashboards = Array.from(uniqueDashboards.values())
                }

                // Deduplicate insights by ID
                if (context.insights) {
                    const uniqueInsights = new Map()
                    context.insights.forEach((insight) => {
                        uniqueInsights.set(insight.id, insight)
                    })
                    context.insights = Array.from(uniqueInsights.values())
                }

                // Add events
                if (contextEvents.length > 0) {
                    context.events = contextEvents
                }

                // Add actions
                if (contextActions.length > 0) {
                    context.actions = contextActions
                }

                return hasData ? context : null
            },
        ],
        hasData: [
            (s: any) => [s.contextInsights, s.contextDashboards, s.contextEvents, s.contextActions],
            (
                contextInsights: MaxInsightContext[],
                contextDashboards: MaxDashboardContext[],
                contextEvents: MaxEventContext[],
                contextActions: MaxActionContext[]
            ): boolean => {
                return [contextInsights, contextDashboards, contextEvents, contextActions].some((arr) => arr.length > 0)
            },
        ],
    }),
    afterMount(({ cache }) => {
        cache.previousLocation = {
            location: router.values.location,
            hashParams: router.values.hashParams,
            searchParams: router.values.searchParams,
        }
    }),
])
