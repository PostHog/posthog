import { IconPageChart } from '@posthog/icons'
import { BuiltLogic, kea } from 'kea'
import { router } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic, RefreshStatus } from 'scenes/dashboard/dashboardLogic'
import { dashboardLogicType } from 'scenes/dashboard/dashboardLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightLogicType } from 'scenes/insights/insightLogicType'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { sceneLogic } from '~/scenes/sceneLogic'
import { ActionType, DashboardType, EventDefinition, QueryBasedInsightModel } from '~/types'

import type { maxContextLogicType } from './maxContextLogicType'
import {
    ActionContextForMax,
    DashboardContextForMax,
    EventContextForMax,
    InsightContextForMax,
    MaxContextOption,
    MaxContextShape,
    MaxNavigationContext,
    MultiActionContextContainer,
    MultiDashboardContextContainer,
    MultiEventContextContainer,
    MultiInsightContextContainer,
} from './maxTypes'

const insightToMaxContext = (insight: Partial<QueryBasedInsightModel>): InsightContextForMax => {
    const source = (insight.query as any).source
    return {
        id: insight.short_id!,
        name: insight.name,
        description: insight.description,
        query: source,
        insight_type: source.kind,
    }
}

const dashboardToMaxContext = (dashboard: DashboardType<QueryBasedInsightModel>): DashboardContextForMax => {
    return {
        id: dashboard.id,
        name: dashboard.name,
        description: dashboard.description,
        insights: dashboard.tiles.filter((tile) => tile.insight).map((tile) => insightToMaxContext(tile.insight!)),
    }
}

const eventToMaxContext = (event: EventDefinition): EventContextForMax => {
    return {
        id: event.id,
        name: event.name,
        description: event.description,
    }
}

const actionToMaxContext = (action: ActionType): ActionContextForMax => {
    return {
        id: action.id,
        name: action.name || `Action ${action.id}`,
        description: action.description || '',
    }
}

export const maxContextLogic = kea<maxContextLogicType>({
    path: ['lib', 'ai', 'maxContextLogic'],
    connect: () => ({
        values: [breadcrumbsLogic({ hashParams: {} }), ['documentTitle']],
        actions: [],
    }),
    actions: {
        enableCurrentPageContext: true,
        disableCurrentPageContext: true,
        addOrUpdateContextInsight: (key: string, data: Partial<QueryBasedInsightModel>) => ({ key, data }),
        addOrUpdateContextDashboard: (key: string, data: DashboardType<QueryBasedInsightModel>) => ({ key, data }),
        addOrUpdateContextEvent: (key: string, data: EventDefinition) => ({ key, data }),
        addOrUpdateContextAction: (key: string, data: ActionType) => ({ key, data }),
        removeContextInsight: (key: string) => ({ key }),
        removeContextDashboard: (key: string) => ({ key }),
        removeContextEvent: (key: string) => ({ key }),
        removeContextAction: (key: string) => ({ key }),
        setNavigationContext: (path: string, pageTitle?: string) => ({ path, pageTitle }),
        clearNavigationContext: true,
        addOrUpdateActiveInsight: (key: string, data: Partial<QueryBasedInsightModel>) => ({ key, data }),
        clearActiveInsights: true,
        setActiveDashboard: (dashboardContext: DashboardType<QueryBasedInsightModel>) => ({ dashboardContext }),
        clearActiveDashboard: true,
        handleTaxonomicFilterChange: (
            value: string | number,
            groupType: TaxonomicFilterGroupType,
            item: DashboardType | QueryBasedInsightModel | EventDefinition | ActionType | string
        ) => ({ value, groupType, item }),
        resetContext: true,
    },
    reducers: {
        useCurrentPageContext: [
            false,
            {
                enableCurrentPageContext: () => true,
                disableCurrentPageContext: () => false,
                resetContext: () => false,
            },
        ],
        contextInsights: [
            {} as MultiInsightContextContainer,
            {
                addOrUpdateContextInsight: (
                    state: MultiInsightContextContainer,
                    { key, data }: { key: string; data: Partial<QueryBasedInsightModel> }
                ) => ({ ...state, [key]: insightToMaxContext(data) }),
                removeContextInsight: (state: MultiInsightContextContainer, { key }: { key: string }) => {
                    const { [key]: _removed, ...rest } = state
                    return rest
                },
                resetContext: () => ({}),
            },
        ],
        contextDashboards: [
            {} as MultiDashboardContextContainer,
            {
                addOrUpdateContextDashboard: (
                    state: MultiDashboardContextContainer,
                    { key, data }: { key: string; data: DashboardType<QueryBasedInsightModel> }
                ) => ({ ...state, [key]: dashboardToMaxContext(data) }),
                removeContextDashboard: (state: MultiDashboardContextContainer, { key }: { key: string }) => {
                    const { [key]: _removed, ...rest } = state
                    return rest
                },
                resetContext: () => ({}),
            },
        ],
        contextEvents: [
            {} as MultiEventContextContainer,
            {
                addOrUpdateContextEvent: (
                    state: MultiEventContextContainer,
                    { key, data }: { key: string; data: EventDefinition }
                ) => ({ ...state, [key]: eventToMaxContext(data) }),
                removeContextEvent: (state: MultiEventContextContainer, { key }: { key: string }) => {
                    const { [key]: _removed, ...rest } = state
                    return rest
                },
                resetContext: () => ({}),
            },
        ],
        contextActions: [
            {} as MultiActionContextContainer,
            {
                addOrUpdateContextAction: (
                    state: MultiActionContextContainer,
                    { key, data }: { key: string; data: ActionType }
                ) => ({ ...state, [key]: actionToMaxContext(data) }),
                removeContextAction: (state: MultiActionContextContainer, { key }: { key: string }) => {
                    const { [key]: _removed, ...rest } = state
                    return rest
                },
                resetContext: () => ({}),
            },
        ],
        activeInsights: [
            {} as MultiInsightContextContainer,
            {
                addOrUpdateActiveInsight: (
                    state: MultiInsightContextContainer,
                    { key, data }: { key: string; data: Partial<QueryBasedInsightModel> }
                ) => ({ ...state, [key]: insightToMaxContext(data) }),
                clearActiveInsights: () => ({}),
            },
        ],
        activeDashboard: [
            null as DashboardContextForMax | null,
            {
                setActiveDashboard: (
                    _: any,
                    { dashboardContext }: { dashboardContext: DashboardType<QueryBasedInsightModel> }
                ) => dashboardToMaxContext(dashboardContext),
                clearActiveDashboard: () => null,
            },
        ],
        navigation: [
            null as MaxNavigationContext | null,
            {
                setNavigationContext: (_: any, { path, pageTitle }: { path: string; pageTitle?: string }) => ({
                    path,
                    page_title: pageTitle,
                }),
                clearNavigationContext: () => null,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        [router.actionTypes.locationChanged]: () => {
            actions.clearActiveInsights()
            actions.clearActiveDashboard()
        },
        [sceneLogic.actionTypes.setScene]: () => {
            // Scene has been set, now update navigation with proper title
            setTimeout(() => {
                actions.setNavigationContext(router.values.location.pathname, values.documentTitle)
            }, 100)
        },
        handleTaxonomicFilterChange: async (
            {
                value,
                groupType,
                item,
            }: {
                value: string | number
                groupType: TaxonomicFilterGroupType
                item: DashboardType | QueryBasedInsightModel | EventDefinition | ActionType | string
            },
            breakpoint
        ) => {
            let dashboardLogicInstance: BuiltLogic<dashboardLogicType> | null = null
            let insightLogicInstance: BuiltLogic<insightLogicType> | null = null
            if (groupType === TaxonomicFilterGroupType.MaxAIContext) {
                if (value === 'current_page') {
                    // Set current page context
                    actions.enableCurrentPageContext()
                }
            } else if (groupType === TaxonomicFilterGroupType.Dashboards) {
                let dashboard = item as DashboardType<QueryBasedInsightModel>
                if (!dashboard.tiles) {
                    dashboardLogicInstance = dashboardLogic.build({
                        id: dashboard.id,
                    })
                    dashboardLogicInstance.mount()

                    // Wait for the dashboard to load
                    dashboardLogicInstance.actions.loadDashboard({
                        action: 'initial_load',
                    })

                    // Use breakpoint for proper async handling instead of while loop
                    await breakpoint(50)
                    while (!dashboardLogicInstance.values.dashboard) {
                        await breakpoint(50)
                    }

                    dashboard = dashboardLogicInstance.values.dashboard!
                }
                actions.addOrUpdateContextDashboard(dashboard.id.toString(), dashboard)
            } else if (groupType === TaxonomicFilterGroupType.Insights) {
                let insight = item as Partial<QueryBasedInsightModel>
                if (!insight.query) {
                    insightLogicInstance = insightLogic.build({
                        dashboardItemId: undefined,
                    })
                    insightLogicInstance.mount()
                    insightLogicInstance.actions.loadInsight(insight.short_id!)

                    // Use breakpoint for proper async handling
                    await breakpoint(50)
                    while (!insightLogicInstance.values.insight.query) {
                        await breakpoint(50)
                    }
                    insight = insightLogicInstance.values.insight!
                }
                actions.addOrUpdateContextInsight(insight.short_id!, insight)
            } else if (groupType === TaxonomicFilterGroupType.Events) {
                const event = item as EventDefinition
                actions.addOrUpdateContextEvent(event.id, event)
            } else if (groupType === TaxonomicFilterGroupType.Actions) {
                const action = item as ActionType
                actions.addOrUpdateContextAction(action.id.toString(), action)
            }
            if (insightLogicInstance) {
                insightLogicInstance.unmount()
            }
            if (dashboardLogicInstance) {
                // wait until all dashboard items are refreshed
                // this allows Max to query cached insights and speed up the response
                while (
                    Object.values(dashboardLogicInstance.values.refreshStatus).some(
                        (status: RefreshStatus) => status.loading
                    )
                ) {
                    await breakpoint(50)
                }
                dashboardLogicInstance.unmount()
            }
        },
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            actions.setNavigationContext(router.values.location.pathname, values.documentTitle)
        },
    }),
    selectors: {
        contextOptions: [
            (s: any) => [s.activeInsights, s.activeDashboard],
            (
                activeInsights: MultiInsightContextContainer,
                activeDashboard: DashboardContextForMax | null
            ): MaxContextOption[] => {
                if (Object.values(activeInsights).length === 0 && !activeDashboard) {
                    return []
                }
                return [
                    {
                        name: 'Current page',
                        value: 'current_page',
                        icon: IconPageChart,
                        items: {
                            insights: Object.values(activeInsights),
                            dashboards: activeDashboard ? [activeDashboard] : [],
                        },
                    },
                ]
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
                s.navigation,
                s.contextDashboards,
                s.useCurrentPageContext,
                s.activeInsights,
                s.activeDashboard,
                s.contextEvents,
                s.contextActions,
                s.dashboardInsightIds,
            ],
            (
                hasData: boolean,
                contextInsights: MultiInsightContextContainer | null,
                navigation: MaxNavigationContext | null,
                contextDashboards: MultiDashboardContextContainer | null,
                useCurrentPageContext: boolean,
                activeInsights: MultiInsightContextContainer | null,
                activeDashboard: DashboardContextForMax | null,
                contextEvents: MultiEventContextContainer | null,
                contextActions: MultiActionContextContainer | null
            ): MaxContextShape | null => {
                const context: MaxContextShape = {}

                // Add context dashboards
                if (contextDashboards && Object.keys(contextDashboards).length > 0) {
                    context.dashboards = contextDashboards
                }

                // Add active dashboard if useCurrentPageContext is true
                if (useCurrentPageContext && activeDashboard) {
                    context.dashboards = { ...context.dashboards, [activeDashboard.id]: activeDashboard }
                }

                // Add insights, filtering out those already in dashboards
                const allInsights = useCurrentPageContext ? { ...activeInsights, ...contextInsights } : contextInsights

                if (allInsights && Object.keys(allInsights).length > 0) {
                    context.insights = allInsights
                }
                if (contextEvents && Object.keys(contextEvents).length > 0) {
                    context.events = contextEvents
                }
                if (contextActions && Object.keys(contextActions).length > 0) {
                    context.actions = contextActions
                }

                if (navigation) {
                    context.global_info = { ...(context.global_info || {}), navigation }
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
                contextInsights: MultiInsightContextContainer | null,
                contextDashboards: MultiDashboardContextContainer | null,
                contextEvents: MultiEventContextContainer | null,
                contextActions: MultiActionContextContainer | null,
                useCurrentPageContext: boolean,
                activeInsights: MultiInsightContextContainer | null,
                activeDashboard: DashboardContextForMax | null
            ): boolean => {
                return (
                    Object.keys(contextInsights || {}).length > 0 ||
                    Object.keys(contextDashboards || {}).length > 0 ||
                    Object.keys(contextEvents || {}).length > 0 ||
                    Object.keys(contextActions || {}).length > 0 ||
                    (useCurrentPageContext && Object.keys(activeInsights || {}).length > 0) ||
                    (useCurrentPageContext && Object.keys(activeDashboard || {}).length > 0)
                )
            },
        ],
    },
})
