import { IconDashboard, IconGraph, IconPageChart } from '@posthog/icons'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic, RefreshStatus } from 'scenes/dashboard/dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { ActionType, DashboardType, EventDefinition, InsightShortId, QueryBasedInsightModel } from '~/types'

import type { maxContextLogicType } from './maxContextLogicType'
import {
    MaxActionContext,
    MaxContextOption,
    MaxContextShape,
    MaxDashboardContext,
    MaxEventContext,
    MaxInsightContext,
} from './maxTypes'

// Utility functions for transforming data to max context
const insightToMaxContext = (insight: Partial<QueryBasedInsightModel>): MaxInsightContext => {
    const source = (insight.query as any)?.source
    return {
        id: insight.short_id!,
        name: insight.name,
        description: insight.description,
        query: source,
    }
}

const dashboardToMaxContext = (dashboard: DashboardType<QueryBasedInsightModel>): MaxDashboardContext => {
    return {
        id: dashboard.id,
        name: dashboard.name,
        description: dashboard.description,
        insights: dashboard.tiles.filter((tile) => tile.insight).map((tile) => insightToMaxContext(tile.insight!)),
        filters: dashboard.filters,
    }
}

const eventToMaxContext = (event: EventDefinition): MaxEventContext => {
    return {
        id: event.id,
        name: event.name,
        description: event.description,
    }
}

const actionToMaxContext = (action: ActionType): MaxActionContext => {
    return {
        id: action.id,
        name: action.name || `Action ${action.id}`,
        description: action.description || '',
    }
}

// Generic utility functions for reducers
const createAddOrUpdateReducer =
    <TContext extends { id: string | number }, TInput>(
        transformer: (input: TInput) => TContext,
        getId: (input: TInput) => string | number
    ) =>
    (state: TContext[], input: TInput): TContext[] =>
        state.filter((item) => item.id !== getId(input)).concat(transformer(input))

const createRemoveReducer =
    <TContext extends { id: string | number }>() =>
    (state: TContext[], { id }: { id: string | number }): TContext[] =>
        state.filter((item) => item.id !== id)

const createResetReducer =
    <TContext>() =>
    (): TContext[] =>
        []

// Generic reducer creator
const createEntityReducers = <TContext extends { id: string | number }, TInput>(
    transformer: (input: TInput) => TContext,
    getId: (input: TInput) => string | number
): {
    addOrUpdate: (state: TContext[], input: TInput) => TContext[]
    remove: (state: TContext[], { id }: { id: string | number }) => TContext[]
    reset: () => TContext[]
} => ({
    addOrUpdate: createAddOrUpdateReducer(transformer, getId),
    remove: createRemoveReducer<TContext>(),
    reset: createResetReducer<TContext>(),
})

export const maxContextLogic = kea<maxContextLogicType>([
    path(['lib', 'ai', 'maxContextLogic']),
    connect(() => ({
        values: [insightSceneLogic, ['filtersOverride', 'variablesOverride']],
        actions: [router, ['locationChanged']],
    })),
    actions({
        enableCurrentPageContext: true,
        disableCurrentPageContext: true,
        addOrUpdateContextInsight: (data: Partial<QueryBasedInsightModel>) => ({ data }),
        addOrUpdateContextDashboard: (data: DashboardType<QueryBasedInsightModel>) => ({ data }),
        addOrUpdateContextEvent: (data: EventDefinition) => ({ data }),
        addOrUpdateContextAction: (data: ActionType) => ({ data }),
        removeContextInsight: (id: string | number) => ({ id }),
        removeContextDashboard: (id: string | number) => ({ id }),
        removeContextEvent: (id: string | number) => ({ id }),
        removeContextAction: (id: string | number) => ({ id }),
        addOrUpdateActiveInsight: (data: Partial<QueryBasedInsightModel>, autoAdd: boolean) => ({
            data,
            autoAdd,
        }),
        clearActiveInsights: true,
        setActiveDashboard: (data: DashboardType<QueryBasedInsightModel>) => ({ data }),
        clearActiveDashboard: true,
        setSelectedContextOption: (value: string) => ({ value }),
        handleTaxonomicFilterChange: (
            value: string | number,
            groupType: TaxonomicFilterGroupType,
            item: DashboardType | QueryBasedInsightModel | EventDefinition | ActionType | MaxContextOption
        ) => ({ value, groupType, item }),
        resetContext: true,
    }),
    reducers(() => {
        const insightReducers = createEntityReducers(insightToMaxContext, (insight) => insight.short_id!)
        const dashboardReducers = createEntityReducers(dashboardToMaxContext, (dashboard) => dashboard.id)
        const eventReducers = createEntityReducers(eventToMaxContext, (event) => event.id)
        const actionReducers = createEntityReducers(actionToMaxContext, (action) => action.id)

        return {
            useCurrentPageContext: [
                false,
                {
                    enableCurrentPageContext: () => true,
                    disableCurrentPageContext: () => false,
                    resetContext: () => false,
                },
            ],
            contextInsights: [
                [] as MaxInsightContext[],
                {
                    addOrUpdateContextInsight: (
                        state: MaxInsightContext[],
                        { data }: { data: Partial<QueryBasedInsightModel> }
                    ) => insightReducers.addOrUpdate(state, data),
                    removeContextInsight: insightReducers.remove,
                    resetContext: insightReducers.reset,
                    addOrUpdateActiveInsight: (
                        state: MaxInsightContext[],
                        { data, autoAdd }: { data: Partial<QueryBasedInsightModel>; autoAdd: boolean }
                    ) => (autoAdd ? insightReducers.addOrUpdate(state, data) : state),
                },
            ],
            contextDashboards: [
                [] as MaxDashboardContext[],
                {
                    addOrUpdateContextDashboard: (
                        state: MaxDashboardContext[],
                        { data }: { data: DashboardType<QueryBasedInsightModel> }
                    ) => dashboardReducers.addOrUpdate(state, data),
                    removeContextDashboard: dashboardReducers.remove,
                    resetContext: dashboardReducers.reset,
                },
            ],
            contextEvents: [
                [] as MaxEventContext[],
                {
                    addOrUpdateContextEvent: (state: MaxEventContext[], { data }: { data: EventDefinition }) =>
                        eventReducers.addOrUpdate(state, data),
                    removeContextEvent: eventReducers.remove,
                    resetContext: eventReducers.reset,
                },
            ],
            contextActions: [
                [] as MaxActionContext[],
                {
                    addOrUpdateContextAction: (state: MaxActionContext[], { data }: { data: ActionType }) =>
                        actionReducers.addOrUpdate(state, data),
                    removeContextAction: actionReducers.remove,
                    resetContext: actionReducers.reset,
                },
            ],
            activeInsights: [
                [] as MaxInsightContext[],
                {
                    addOrUpdateActiveInsight: (
                        state: MaxInsightContext[],
                        { data }: { data: Partial<QueryBasedInsightModel> }
                    ) => insightReducers.addOrUpdate(state, data),
                    clearActiveInsights: insightReducers.reset,
                },
            ],
            activeDashboard: [
                null as MaxDashboardContext | null,
                {
                    setActiveDashboard: (_: any, { data }: { data: DashboardType<QueryBasedInsightModel> }) =>
                        dashboardToMaxContext(data),
                    clearActiveDashboard: () => null,
                },
            ],
        }
    }),
    listeners(({ actions }) => ({
        locationChanged: () => {
            actions.resetContext()
            actions.clearActiveInsights()
            actions.clearActiveDashboard()
        },
        handleTaxonomicFilterChange: async (
            {
                value,
                groupType,
                item,
            }: {
                value: string | number
                groupType: TaxonomicFilterGroupType
                item: DashboardType | QueryBasedInsightModel | EventDefinition | ActionType | MaxContextOption
            },
            breakpoint
        ) => {
            try {
                // Handle current page context selection
                if (groupType === TaxonomicFilterGroupType.MaxAIContext && value === 'current_page') {
                    actions.enableCurrentPageContext()
                    return
                }

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
                    let dashboard = itemInfo.preloaded as DashboardType<QueryBasedInsightModel> | null

                    if (!dashboard || !dashboard.tiles) {
                        const dashboardLogicInstance = dashboardLogic.build({ id: itemInfo.id as number })
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

                    actions.addOrUpdateContextDashboard(dashboard)
                }

                // Handle insight selection
                if (itemInfo.type === 'insight') {
                    let insight = itemInfo.preloaded as QueryBasedInsightModel | null

                    if (!insight || !insight.query) {
                        const insightLogicInstance = insightLogic.build({ dashboardItemId: undefined })
                        insightLogicInstance.mount()

                        try {
                            insightLogicInstance.actions.loadInsight(itemInfo.id as InsightShortId)

                            await breakpoint(50)
                            while (!insightLogicInstance.values.insight.query) {
                                await breakpoint(50)
                            }

                            insight = insightLogicInstance.values.insight as QueryBasedInsightModel
                        } finally {
                            insightLogicInstance.unmount()
                        }
                    }

                    actions.addOrUpdateContextInsight(insight)
                }
            } catch (error) {
                console.error('Error handling taxonomic filter change:', error)
            }
        },
    })),
    selectors({
        contextOptions: [
            (s: any) => [s.activeInsights, s.activeDashboard, s.contextInsights, s.contextDashboards],
            (activeInsights: MaxInsightContext[], activeDashboard: MaxDashboardContext | null): MaxContextOption[] => {
                const options: MaxContextOption[] = []

                // Add Current page option if there are active items
                if (activeInsights.length > 0 || activeDashboard) {
                    options.push({
                        id: 'current_page',
                        name: 'Current page',
                        value: 'current_page',
                        icon: IconPageChart,
                        items: {
                            insights: activeInsights,
                            dashboards: activeDashboard ? [activeDashboard] : [],
                        },
                    })
                }

                // Add individual dashboards from context
                if (activeDashboard) {
                    options.push({
                        id: activeDashboard.id.toString(),
                        name: activeDashboard.name || `Dashboard ${activeDashboard.id}`,
                        value: activeDashboard.id,
                        type: 'dashboard',
                        icon: IconDashboard,
                    })
                }

                // Add individual insights from context
                if (activeInsights.length > 0) {
                    activeInsights.forEach((insight) => {
                        options.push({
                            id: insight.id.toString(),
                            name: insight.name || `Insight ${insight.id}`,
                            value: insight.id,
                            type: 'insight',
                            icon: IconGraph,
                        })
                    })
                }

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
                s.useCurrentPageContext,
                s.activeInsights,
                s.activeDashboard,
                s.filtersOverride,
                s.variablesOverride,
            ],
            (
                hasData: boolean,
                contextInsights: MaxInsightContext[],
                contextDashboards: MaxDashboardContext[],
                contextEvents: MaxEventContext[],
                contextActions: MaxActionContext[],
                useCurrentPageContext: boolean,
                activeInsights: MaxInsightContext[],
                activeDashboard: MaxDashboardContext | null,
                filtersOverride: DashboardFilter,
                variablesOverride: Record<string, HogQLVariable> | null
            ): MaxContextShape | null => {
                const context: MaxContextShape = {}

                // Add context dashboards
                if (Object.keys(contextDashboards).length > 0) {
                    context.dashboards = Object.values(contextDashboards)
                }

                // Add active dashboard if useCurrentPageContext is true
                if (useCurrentPageContext && activeDashboard) {
                    context.dashboards = Object.values(context.dashboards || {}).concat(activeDashboard)
                }

                // Add insights, filtering out those already in dashboards
                const allInsights = useCurrentPageContext
                    ? [...(activeInsights || []), ...(contextInsights || [])]
                    : contextInsights

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

                if (Object.keys(contextEvents).length > 0) {
                    context.events = contextEvents
                }
                if (Object.keys(contextActions).length > 0) {
                    context.actions = contextActions
                }

                return hasData ? context : null
            },
        ],
        hasData: [
            (s: any) => [
                s.contextInsights,
                s.contextDashboards,
                s.contextEvents,
                s.contextActions,
                s.useCurrentPageContext,
                s.activeInsights,
                s.activeDashboard,
            ],
            (
                contextInsights: MaxInsightContext[],
                contextDashboards: MaxDashboardContext[],
                contextEvents: MaxEventContext[],
                contextActions: MaxActionContext[],
                useCurrentPageContext: boolean,
                activeInsights: MaxInsightContext[],
                activeDashboard: MaxDashboardContext | null
            ): boolean => {
                return (
                    contextInsights.length > 0 ||
                    contextDashboards.length > 0 ||
                    contextEvents.length > 0 ||
                    contextActions.length > 0 ||
                    (useCurrentPageContext && activeInsights && activeInsights.length > 0) ||
                    (useCurrentPageContext && activeDashboard !== null)
                )
            },
        ],
    }),
])
