import { IconDashboard, IconGraph } from '@posthog/icons'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import {
    ActionType,
    BillingType,
    DashboardType,
    EventDefinition,
    InsightShortId,
    QueryBasedInsightModel,
    TeamType,
} from '~/types'

import type { maxContextLogicType } from './maxContextLogicType'
import {
    InsightWithQuery,
    MaxActionContext,
    MaxContextItem,
    MaxContextTaxonomicFilterOption,
    MaxUIContext,
    MaxContextType,
    MaxDashboardContext,
    MaxEventContext,
    MaxInsightContext,
    MaxContextInput,
    MaxBillingContext,
} from './maxTypes'
import { subscriptions } from 'kea-subscriptions'
import { dashboardLogic, RefreshStatus } from 'scenes/dashboard/dashboardLogic'
import {
    actionToMaxContextPayload,
    billingToMaxContext,
    dashboardToMaxContext,
    eventToMaxContextPayload,
    insightToMaxContext,
} from './utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingUsageLogic } from 'scenes/billing/billingUsageLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pipelineDestinationsLogic } from 'scenes/pipeline/destinations/destinationsLogic'
import { DESTINATION_TYPES } from 'scenes/pipeline/destinations/constants'
import { Destination } from 'scenes/pipeline/types'

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

// Generic utility functions for reducers
const sceneContextReducer = <TContext extends EntityWithIdAndType>(
    type: string,
    sceneContext: EntityWithIdAndType[]
): TContext[] => sceneContext.filter((item): item is TContext => item.type === type)

const addOrUpdateEntity = <TContext extends EntityWithIdAndType>(state: TContext[], entity: TContext): TContext[] =>
    state.filter((item) => item.id !== entity.id).concat(entity)

const removeEntity = <TContext extends EntityWithIdAndType>(state: TContext[], id: string | number): TContext[] =>
    state.filter((item) => item.id !== id)

export type LoadedEntitiesMap = { dashboard: number[]; insight: string[] }

export const maxContextLogic = kea<maxContextLogicType>([
    path(['lib', 'ai', 'maxContextLogic']),
    connect(() => ({
        values: [
            insightSceneLogic,
            ['filtersOverride', 'variablesOverride'],
            sceneLogic,
            ['activeScene', 'activeSceneLogic', 'activeLoadedScene'],
            billingLogic,
            ['billing'],
            billingUsageLogic,
            ['billingUsageResponse', 'dateFrom as billingUsageDateFrom', 'dateTo as billingUsageDateTo'],
            organizationLogic,
            ['isAdminOrOwner'],
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
            pipelineDestinationsLogic({ types: DESTINATION_TYPES }),
            ['destinations'],
        ],
        actions: [
            router,
            ['locationChanged'],
            billingLogic,
            ['loadBilling'],
            billingUsageLogic,
            ['loadBillingUsage', 'setDateRange as billingUsageSetDateRange', 'setFilters'],
        ],
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
        loadBillingContext: true,
        resetContext: true,
        applyContext: (context: MaxContextItem[]) => ({ context }),
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
                applyContext: (_: MaxInsightContext[], { context }: { context: MaxContextItem[] }) =>
                    sceneContextReducer(MaxContextType.INSIGHT, context),
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
                applyContext: (_: MaxDashboardContext[], { context }: { context: MaxContextItem[] }) =>
                    sceneContextReducer(MaxContextType.DASHBOARD, context),
            },
        ],
        contextEvents: [
            [] as MaxEventContext[],
            {
                addOrUpdateContextEvent: (state: MaxEventContext[], { data }: { data: EventDefinition }) =>
                    addOrUpdateEntity(state, eventToMaxContextPayload(data)),
                removeContextEvent: (state: MaxEventContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                applyContext: (_: MaxEventContext[], { context }: { context: MaxContextItem[] }) =>
                    sceneContextReducer(MaxContextType.EVENT, context),
            },
        ],
        contextActions: [
            [] as MaxActionContext[],
            {
                addOrUpdateContextAction: (state: MaxActionContext[], { data }: { data: ActionType }) =>
                    addOrUpdateEntity(state, actionToMaxContextPayload(data)),
                removeContextAction: (state: MaxActionContext[], { id }: { id: string | number }) =>
                    removeEntity(state, id),
                applyContext: (_: MaxActionContext[], { context }: { context: MaxContextItem[] }) =>
                    sceneContextReducer(MaxContextType.ACTION, context),
            },
        ],
    }),
    listeners(({ actions, cache, values }) => ({
        loadBillingContext: async () => {
            // Check if user has access to billing data
            if (!values.isAdminOrOwner) {
                return
            }
            // Load billing data
            actions.loadBilling()

            // Set date range for last 30 days and load usage with weekly interval
            const endDate = new Date()
            endDate.setDate(endDate.getDate() - 1) // Yesterday as today's usage is not available yet
            const startDate = new Date()
            startDate.setDate(startDate.getDate() - 31) // 30 days ago

            actions.billingUsageSetDateRange(
                startDate.toISOString().split('T')[0],
                endDate.toISOString().split('T')[0],
                false
            )

            // Set weekly interval for billing usage
            actions.setFilters({ interval: 'week' }, false)
            actions.loadBillingUsage()
        },
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

            if (dashboard) {
                actions.addOrUpdateContextDashboard(dashboard)
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

            if (insight) {
                actions.addOrUpdateContextInsight(insight)
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
                    actions.loadAndProcessInsight({
                        id: itemInfo.id as InsightShortId,
                        preloaded: itemInfo.preloaded as QueryBasedInsightModel | null,
                    })
                }
            } catch (error) {
                console.error('Error handling taxonomic filter change:', error)
            }
        },
        resetContext: () => {
            actions.applyContext(values.sceneContext)
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
                                return insightToMaxContext(item.data)
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
        billingContext: [
            (s: any) => [
                s.billing,
                s.billingUsageResponse,
                s.isAdminOrOwner,
                s.currentTeam,
                s.featureFlags,
                s.destinations,
            ],
            (
                billing: BillingType | null,
                billingUsageResponse: any,
                isAdminOrOwner: boolean,
                currentTeam: TeamType,
                featureFlags: Record<string, any>,
                destinations: Destination[]
            ): MaxBillingContext | null => {
                if (!isAdminOrOwner) {
                    return null
                }
                return billingToMaxContext(billing, featureFlags, currentTeam, destinations, billingUsageResponse)
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
                s.billingContext,
            ],
            (
                hasData: boolean,
                contextInsights: MaxInsightContext[],
                contextDashboards: MaxDashboardContext[],
                contextEvents: MaxEventContext[],
                contextActions: MaxActionContext[],
                filtersOverride: DashboardFilter,
                variablesOverride: Record<string, HogQLVariable> | null,
                billingContext: MaxBillingContext | null
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

                // Add global filters and variables override if present
                if (filtersOverride) {
                    context.filters_override = filtersOverride
                }

                if (variablesOverride) {
                    context.variables_override = variablesOverride
                }

                if (billingContext) {
                    context.billing = billingContext
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
        rawSceneContext: (rawContext: MaxContextInput[]) => {
            rawContext.forEach((item: MaxContextInput) => {
                if (
                    item.type === MaxContextType.INSIGHT &&
                    item.data.short_id &&
                    !values.loadedEntities.insight.includes(item.data.short_id)
                ) {
                    actions.loadAndProcessInsight({
                        id: item.data.short_id,
                        preloaded: item.data as QueryBasedInsightModel,
                    })
                } else if (
                    item.type === MaxContextType.DASHBOARD &&
                    item.data.id &&
                    !values.loadedEntities.dashboard.includes(item.data.id)
                ) {
                    actions.loadAndProcessDashboard({ id: item.data.id, preloaded: item.data })
                }
            })
        },
        sceneContext: (context: MaxContextItem[]) => {
            actions.applyContext(context)
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
