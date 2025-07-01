import { IconDashboard, IconGraph } from '@posthog/icons'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { ActionType, DashboardType, EventDefinition, InsightShortId, QueryBasedInsightModel } from '~/types'

import type { maxContextLogicType } from './maxContextLogicType'
import {
    InsightWithQuery,
    MaxActionContext,
    MaxContextItem,
    MaxContextOption,
    MaxContextShape,
    MaxDashboardContext,
    MaxEventContext,
    MaxInsightContext,
    RawMaxContextItem,
} from './maxTypes'
import { subscriptions } from 'kea-subscriptions'
import { dashboardLogic, RefreshStatus } from 'scenes/dashboard/dashboardLogic'
import { actionToMaxContext, dashboardToMaxContext, eventToMaxContext, insightToMaxContext } from './utils'

// Type definitions for better reusability
export type TaxonomicItem = DashboardType | QueryBasedInsightModel | EventDefinition | ActionType | MaxContextOption

export type DashboardItemInfo = { id: number; preloaded: DashboardType<QueryBasedInsightModel> | null }
export type InsightItemInfo = { id: InsightShortId; preloaded: QueryBasedInsightModel | null }

type EntityWithIdAndType = { id: string | number; type: string }

// Generic utility functions for reducers
const sceneContextReducer = <TContext extends EntityWithIdAndType>(
    type: string,
    sceneContext: EntityWithIdAndType[]
): TContext[] => sceneContext.filter((item): item is TContext => item.type === type)

const addOrUpdateEntity = <TContext extends EntityWithIdAndType>(state: TContext[], entity: TContext): TContext[] =>
    state.filter((item) => item.id !== entity.id).concat(entity)

const removeEntity = <TContext extends EntityWithIdAndType>(state: TContext[], id: string | number): TContext[] =>
    state.filter((item) => item.id !== id)

const resetEntities = <TContext>(): TContext[] => []

const autoAddEntities = <TContext extends EntityWithIdAndType>(
    state: TContext[],
    newEntities: TContext[]
): TContext[] => {
    const existingIds = new Set(state.map((entity) => entity.id))
    const uniqueNewEntities = newEntities.filter((entity) => !existingIds.has(entity.id))
    return [...state, ...uniqueNewEntities]
}

export type LoadedEntitiesMap = { dashboard: []; insight: [] }

export const maxContextLogic = kea<maxContextLogicType>([
    path(['lib', 'ai', 'maxContextLogic']),
    connect(() => ({
        values: [
            insightSceneLogic,
            ['filtersOverride', 'variablesOverride'],
            sceneLogic,
            ['activeScene', 'activeSceneLogic', 'activeLoadedScene'],
        ],
        actions: [router, ['locationChanged']],
    })),
    actions({
        addOrUpdateContextInsight: (data: InsightWithQuery) => ({ data }),
        addOrUpdateContextDashboard: (data: DashboardType<QueryBasedInsightModel>) => ({ data }),
        addOrUpdateContextEvent: (data: EventDefinition) => ({ data }),
        addOrUpdateContextAction: (data: ActionType) => ({ data }),
        removeContextInsight: (id: string | number) => ({ id }),
        removeContextDashboard: (id: string | number) => ({ id }),
        removeContextEvent: (id: string | number) => ({ id }),
        removeContextAction: (id: string | number) => ({ id }),
        loadAndProcessDashboard: (data: DashboardItemInfo) => ({ data }),
        loadAndProcessInsight: (data: InsightItemInfo) => ({ data }),
        setSelectedContextOption: (value: string) => ({ value }),
        handleTaxonomicFilterChange: (
            value: string | number,
            groupType: TaxonomicFilterGroupType,
            item: TaxonomicItem
        ) => ({ value, groupType, item }),
        resetContext: true,
        autoAddContext: (context: MaxContextItem[]) => ({ context }),
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
                addOrUpdateContextInsight: (state: MaxInsightContext[], { data }: { data: InsightWithQuery }) =>
                    addOrUpdateEntity(state, insightToMaxContext(data)),
                removeContextInsight: (state: MaxInsightContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                resetContext: () => resetEntities<MaxInsightContext>(),
                autoAddContext: (state: MaxInsightContext[], { context }: { context: MaxContextItem[] }) =>
                    autoAddEntities(state, sceneContextReducer('insight', context)),
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
                resetContext: () => resetEntities<MaxDashboardContext>(),
                autoAddContext: (state: MaxDashboardContext[], { context }: { context: MaxContextItem[] }) =>
                    autoAddEntities(state, sceneContextReducer('dashboard', context)),
            },
        ],
        contextEvents: [
            [] as MaxEventContext[],
            {
                addOrUpdateContextEvent: (state: MaxEventContext[], { data }: { data: EventDefinition }) =>
                    addOrUpdateEntity(state, eventToMaxContext(data)),
                removeContextEvent: (state: MaxEventContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                resetContext: () => resetEntities<MaxEventContext>(),
                autoAddContext: (state: MaxEventContext[], { context }: { context: MaxContextItem[] }) =>
                    autoAddEntities(state, sceneContextReducer('event', context)),
            },
        ],
        contextActions: [
            [] as MaxActionContext[],
            {
                addOrUpdateContextAction: (state: MaxActionContext[], { data }: { data: ActionType }) =>
                    addOrUpdateEntity(state, actionToMaxContext(data)),
                removeContextAction: (state: MaxActionContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                resetContext: () => resetEntities<MaxActionContext>(),
                autoAddContext: (state: MaxActionContext[], { context }: { context: MaxContextItem[] }) =>
                    autoAddEntities(state, sceneContextReducer('action', context)),
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

            // Always reset context if pathname or search params changed
            if (
                currentLocation?.pathname !== previousLocation.location?.pathname ||
                !objectsEqual({ ...currentSearchParams }, { ...previousLocation.searchParams })
            ) {
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
                    dashboardLogicInstance.actions.loadDashboard({ action: 'initial_load' })

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
        },
        loadAndProcessInsight: async ({ data }: { data: InsightItemInfo }, breakpoint) => {
            let insight = data.preloaded

            if (!insight || !insight.query) {
                const insightLogicInstance = insightLogic.build({ dashboardItemId: undefined })
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
                        const _item = item as MaxContextOption
                        if (_item.type === 'insight') {
                            return {
                                type: 'insight',
                                id: _item.value,
                                preloaded: null,
                            }
                        }
                        if (_item.type === 'dashboard') {
                            return isNaN(_item.value as number)
                                ? null
                                : {
                                      type: 'dashboard',
                                      id: _item.value,
                                      preloaded: null,
                                  }
                        }
                    }

                    // Handle direct selections
                    if (groupType === TaxonomicFilterGroupType.Dashboards) {
                        const dashboard = item as DashboardType
                        return {
                            type: 'dashboard',
                            id: dashboard.id,
                            preloaded: dashboard as DashboardType<QueryBasedInsightModel>,
                        }
                    }

                    if (groupType === TaxonomicFilterGroupType.Insights) {
                        const insight = item as QueryBasedInsightModel
                        return {
                            type: 'insight',
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
                if (itemInfo.type === 'dashboard') {
                    actions.loadAndProcessDashboard({
                        id: itemInfo.id as number,
                        preloaded: itemInfo.preloaded as DashboardType<QueryBasedInsightModel> | null,
                    })
                }

                // Handle insight selection
                if (itemInfo.type === 'insight') {
                    actions.loadAndProcessInsight({
                        id: itemInfo.id as InsightShortId,
                        preloaded: itemInfo.preloaded as QueryBasedInsightModel | null,
                    })
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
                (state): RawMaxContextItem[] => {
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
            (rawSceneContext: RawMaxContextItem[]): MaxContextItem[] => {
                return rawSceneContext
                    .map((item): MaxContextItem | null => {
                        switch (item.type) {
                            case 'insight':
                                return insightToMaxContext(item.data)
                            case 'dashboard':
                                return dashboardToMaxContext(item.data)
                            case 'event':
                                return eventToMaxContext(item.data)
                            case 'action':
                                return actionToMaxContext(item.data)
                            default:
                                return null
                        }
                    })
                    .filter((item): item is MaxContextItem => item !== null)
            },
        ],
        contextOptions: [
            (s: any) => [s.sceneContext],
            (sceneContext: MaxContextItem[]): MaxContextOption[] => {
                const options: MaxContextOption[] = []
                sceneContext.forEach((item) => {
                    if (item.type == 'insight') {
                        options.push({
                            id: item.id.toString(),
                            name: item.name || `Insight ${item.id}`,
                            value: item.id,
                            type: 'insight',
                            icon: IconGraph,
                        })
                    } else if (item.type == 'dashboard') {
                        options.push({
                            id: item.id.toString(),
                            name: item.name || `Dashboard ${item.id}`,
                            value: item.id,
                            type: 'dashboard',
                            icon: IconDashboard,
                        })
                        item.insights.forEach((insight) => {
                            options.push({
                                id: insight.id.toString(),
                                name: insight.name || `Insight ${insight.id}`,
                                value: insight.id,
                                type: 'insight',
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
            (contextOptions: MaxContextOption[]): TaxonomicFilterGroupType => {
                return contextOptions.length > 0
                    ? TaxonomicFilterGroupType.MaxAIContext
                    : TaxonomicFilterGroupType.Events
            },
        ],
        taxonomicGroupTypes: [
            (s: any) => [s.contextOptions],
            (contextOptions: MaxContextOption[]): TaxonomicFilterGroupType[] => {
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
            (s: any) => [
                s.hasData,
                s.contextInsights,
                s.contextDashboards,
                s.contextEvents,
                s.contextActions,
                s.filtersOverride,
                s.variablesOverride,
            ],
            (
                hasData: boolean,
                contextInsights: MaxInsightContext[],
                contextDashboards: MaxDashboardContext[],
                contextEvents: MaxEventContext[],
                contextActions: MaxActionContext[],
                filtersOverride: DashboardFilter,
                variablesOverride: Record<string, HogQLVariable> | null
            ): MaxContextShape | null => {
                const context: MaxContextShape = {}

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

                // Add global filters and variables override if present
                if (filtersOverride) {
                    context.filters_override = filtersOverride
                }

                if (variablesOverride) {
                    context.variables_override = variablesOverride
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
    subscriptions(({ values, actions }) => ({
        rawSceneContext: (rawContext: RawMaxContextItem[]) => {
            rawContext.forEach((item: RawMaxContextItem) => {
                if (
                    item.type === 'insight' &&
                    item.data.short_id &&
                    !values.loadedEntities.insight.includes(item.data.short_id)
                ) {
                    actions.loadAndProcessInsight({
                        id: item.data.short_id,
                        preloaded: item.data as QueryBasedInsightModel,
                    })
                } else if (
                    item.type === 'dashboard' &&
                    item.data.id &&
                    !values.loadedEntities.dashboard.includes(item.data.id)
                ) {
                    actions.loadAndProcessDashboard({ id: item.data.id, preloaded: item.data })
                }
            })
        },
        sceneContext: (context: MaxContextItem[]) => {
            actions.autoAddContext(context)
        },
    })),
    afterMount(({ cache }) => {
        cache.previousLocation = {
            location: router.values.location,
            hashParams: router.values.hashParams,
            searchParams: router.values.searchParams,
        }
    }),
])
