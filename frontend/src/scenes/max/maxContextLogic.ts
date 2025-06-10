import { IconPageChart } from '@posthog/icons'
import { actions, BuiltLogic, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic, RefreshStatus } from 'scenes/dashboard/dashboardLogic'
import { dashboardLogicType } from 'scenes/dashboard/dashboardLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { ActionType, DashboardType, EventDefinition, QueryBasedInsightModel } from '~/types'

import type { maxContextLogicType } from './maxContextLogicType'
import { MaxContextOption, MaxContextShape, MaxDashboardContext, MaxInsightContext } from './maxTypes'

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

export const maxContextLogic = kea<maxContextLogicType>([
    path(['lib', 'ai', 'maxContextLogic']),
    connect(() => ({
        values: [insightSceneLogic, ['filtersOverride', 'variablesOverride']],
        actions: [router, ['locationChanged']],
    })),
    actions({
        enableCurrentPageContext: true,
        disableCurrentPageContext: true,
        addOrUpdateContextInsight: (insight: Partial<QueryBasedInsightModel>) => ({ insight }),
        addOrUpdateContextDashboard: (dashboard: DashboardType<QueryBasedInsightModel>) => ({ dashboard }),
        removeContextInsight: (id: string | number) => ({ id }),
        removeContextDashboard: (id: string | number) => ({ id }),
        addOrUpdateActiveInsight: (insight: Partial<QueryBasedInsightModel>, autoAdd: boolean) => ({
            insight,
            autoAdd,
        }),
        clearActiveInsights: true,
        setActiveDashboard: (dashboardContext: DashboardType<QueryBasedInsightModel>) => ({ dashboardContext }),
        clearActiveDashboard: true,
        handleTaxonomicFilterChange: (
            value: string | number,
            groupType: TaxonomicFilterGroupType,
            item: DashboardType | QueryBasedInsightModel | EventDefinition | ActionType | string
        ) => ({ value, groupType, item }),
        resetContext: true,
    }),
    reducers({
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
                addOrUpdateActiveInsight: (
                    state: MaxInsightContext[],
                    { insight, autoAdd }: { insight: Partial<QueryBasedInsightModel>; autoAdd: boolean }
                ) => {
                    if (autoAdd) {
                        return state
                            .filter((stateInsight) => stateInsight.id !== insight.short_id)
                            .concat(insightToMaxContext(insight))
                    }
                    return state
                },
                addOrUpdateContextInsight: (
                    state: MaxInsightContext[],
                    { insight }: { insight: Partial<QueryBasedInsightModel> }
                ) =>
                    state
                        .filter((stateInsight) => stateInsight.id !== insight.short_id)
                        .concat(insightToMaxContext(insight)),
                removeContextInsight: (state: MaxInsightContext[], { id }: { id: string | number }) => {
                    return state.filter((insight) => insight.id !== id)
                },
                resetContext: () => [],
            },
        ],
        contextDashboards: [
            [] as MaxDashboardContext[],
            {
                addOrUpdateContextDashboard: (
                    state: MaxDashboardContext[],
                    { dashboard }: { dashboard: DashboardType<QueryBasedInsightModel> }
                ) =>
                    state
                        .filter((stateDashboard) => stateDashboard.id !== dashboard.id)
                        .concat(dashboardToMaxContext(dashboard)),
                removeContextDashboard: (state: MaxDashboardContext[], { id }: { id: string | number }) => {
                    return state.filter((dashboard) => dashboard.id !== id)
                },
                resetContext: () => [],
            },
        ],
        activeInsights: [
            [] as MaxInsightContext[],
            {
                addOrUpdateActiveInsight: (
                    state: MaxInsightContext[],
                    { insight }: { insight: Partial<QueryBasedInsightModel> }
                ) =>
                    state
                        .filter((stateInsight) => stateInsight.id !== insight.short_id)
                        .concat(insightToMaxContext(insight)),
                clearActiveInsights: () => [],
            },
        ],
        activeDashboard: [
            null as MaxDashboardContext | null,
            {
                setActiveDashboard: (
                    _: any,
                    { dashboardContext }: { dashboardContext: DashboardType<QueryBasedInsightModel> }
                ) => dashboardToMaxContext(dashboardContext),
                clearActiveDashboard: () => null,
            },
        ],
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
                actions.addOrUpdateContextDashboard(dashboard)
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
                actions.addOrUpdateContextInsight(insight)
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
    })),
    selectors({
        contextOptions: [
            (s: any) => [s.activeInsights, s.activeDashboard],
            (activeInsights: MaxInsightContext[], activeDashboard: MaxDashboardContext | null): MaxContextOption[] => {
                if (activeInsights.length === 0 && !activeDashboard) {
                    return []
                }
                return [
                    {
                        name: 'Current page',
                        value: 'current_page',
                        icon: IconPageChart,
                        items: {
                            insights: activeInsights,
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
                    : TaxonomicFilterGroupType.Insights
            },
        ],
        taxonomicGroupTypes: [
            (s: any) => [s.contextOptions],
            (contextOptions: MaxContextOption[]): TaxonomicFilterGroupType[] => {
                const groupTypes: TaxonomicFilterGroupType[] = []
                if (contextOptions.length > 0) {
                    groupTypes.push(TaxonomicFilterGroupType.MaxAIContext)
                }
                groupTypes.push(TaxonomicFilterGroupType.Insights, TaxonomicFilterGroupType.Dashboards)
                return groupTypes
            },
        ],
        compiledContext: [
            (s: any) => [
                s.hasData,
                s.contextInsights,
                s.contextDashboards,
                s.useCurrentPageContext,
                s.activeInsights,
                s.activeDashboard,
                s.filtersOverride,
                s.variablesOverride,
            ],
            (
                hasData: boolean,
                contextInsights: MaxInsightContext[] | null,
                contextDashboards: MaxDashboardContext[] | null,
                useCurrentPageContext: boolean,
                activeInsights: MaxInsightContext[] | null,
                activeDashboard: MaxDashboardContext | null,
                filtersOverride: DashboardFilter,
                variablesOverride: Record<string, HogQLVariable> | null
            ): MaxContextShape | null => {
                const context: MaxContextShape = {}

                // Add context dashboards
                if (contextDashboards && Object.keys(contextDashboards).length > 0) {
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

                if (allInsights && allInsights.length > 0) {
                    context.insights = allInsights
                }

                // Add global filters and variables override if present
                if (filtersOverride) {
                    context.filters_override = filtersOverride
                }
                if (variablesOverride) {
                    context.variables_override = variablesOverride
                }

                return hasData ? context : null
            },
        ],
        hasData: [
            (s: any) => [
                s.contextInsights,
                s.contextDashboards,
                s.useCurrentPageContext,
                s.activeInsights,
                s.activeDashboard,
            ],
            (
                contextInsights: MaxInsightContext[] | null,
                contextDashboards: MaxDashboardContext[] | null,
                useCurrentPageContext: boolean,
                activeInsights: MaxInsightContext[] | null,
                activeDashboard: MaxDashboardContext | null
            ): boolean => {
                return (
                    (contextInsights && contextInsights.length > 0) ||
                    (contextDashboards && contextDashboards.length > 0) ||
                    (useCurrentPageContext && activeInsights && activeInsights.length > 0) ||
                    (useCurrentPageContext && activeDashboard !== null)
                )
            },
        ],
    }),
])
