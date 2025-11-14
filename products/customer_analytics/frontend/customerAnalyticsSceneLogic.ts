import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ActionsNode, EventsNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, Breadcrumb, ChartDisplayType, FilterType, InsightType } from '~/types'

import { InsightDefinition } from 'products/customer_analytics/frontend/insightDefinitions'
import { CustomerAnalyticsEventsConfig } from 'products/customer_analytics/frontend/types'

import type { customerAnalyticsSceneLogicType } from './customerAnalyticsSceneLogicType'

export interface CustomerAnalyticsSceneLogicProps {
    tabId: string
}

export const customerAnalyticsSceneLogic = kea<customerAnalyticsSceneLogicType>([
    path(['scenes', 'customerAnalytics', 'customerAnalyticsScene']),
    tabAwareScene(),
    connect(() => ({
        values: [teamLogic, ['currentTeamId', 'currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    actions({
        setActivityEventSelection: (filters: FilterType) => ({
            filters,
        }),
        saveActivityEvent: true,
        toggleEventConfigModal: (isOpen?: boolean) => ({ isOpen }),
    }),
    reducers({
        activityEventSelection: [
            null as FilterType | null,
            {
                setActivityEventSelection: (_, { filters }) => filters,
            },
        ],
        isEventConfigModalOpen: [
            false,
            {
                toggleEventConfigModal: (state, { isOpen }) => (isOpen !== undefined ? isOpen : !state),
            },
        ],
    }),
    selectors({
        tabId: [() => [(_, props: CustomerAnalyticsSceneLogicProps) => props.tabId], (tabIdProp): string => tabIdProp],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.CustomerAnalytics,
                    name: sceneConfigurations[Scene.CustomerAnalytics].name,
                    path: urls.customerAnalytics(),
                    iconType: sceneConfigurations[Scene.CustomerAnalytics].iconType || 'default_icon_type',
                },
            ],
        ],
        activityEventSelectionWithDefault: [
            (s) => [s.activityEventSelection, s.activityEvent],
            (
                activityEventSelection: FilterType | null,
                activityEvent: (EventsNode | ActionsNode) | null
            ): FilterType => {
                if (activityEventSelection) {
                    return activityEventSelection
                }
                // Convert activity event to FilterType format using the conversion helper
                const converted = seriesToActionsAndEvents(activityEvent ? [activityEvent] : [])
                return {
                    insight: InsightType.TRENDS,
                    ...converted,
                }
            },
        ],
        hasActivityEventChanged: [
            (s) => [s.activityEventSelection],
            (activityEventSelection): boolean => {
                return activityEventSelection !== null
            },
        ],
        customerAnalyticsEvents: [
            (s) => [s.currentTeam],
            (currentTeam): CustomerAnalyticsEventsConfig =>
                ((currentTeam?.extra_settings as any)?.customer_analytics_events as CustomerAnalyticsEventsConfig) || {
                    activity_event: null,
                },
        ],
        activityEvent: [
            (s) => [s.customerAnalyticsEvents],
            (customerAnalyticsEvents: CustomerAnalyticsEventsConfig): EventsNode | ActionsNode => {
                // Default to $pageview if no event configured
                if (!customerAnalyticsEvents.activity_event) {
                    return {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        math: BaseMathType.UniqueUsers,
                        properties: [],
                    }
                }
                return customerAnalyticsEvents.activity_event
            },
        ],
        dauSeries: [
            (s) => [s.activityEvent],
            (activityEvent: EventsNode | ActionsNode): EventsNode | ActionsNode => {
                return {
                    ...activityEvent,
                    math: BaseMathType.UniqueUsers,
                }
            },
        ],
        wauSeries: [
            (s) => [s.activityEvent],
            (activityEvent: EventsNode | ActionsNode): EventsNode | ActionsNode => {
                return {
                    ...activityEvent,
                    math: BaseMathType.WeeklyActiveUsers,
                }
            },
        ],
        mauSeries: [
            (s) => [s.activityEvent],
            (activityEvent: EventsNode | ActionsNode): EventsNode | ActionsNode => {
                return {
                    ...activityEvent,
                    math: BaseMathType.MonthlyActiveUsers,
                }
            },
        ],
        activeUsersInsights: [
            (s) => [s.dauSeries, s.wauSeries, s.mauSeries],
            (
                dauSeries: EventsNode | ActionsNode,
                wauSeries: EventsNode | ActionsNode,
                mauSeries: EventsNode | ActionsNode
            ): InsightDefinition[] => [
                {
                    name: 'Active Users (DAU/WAU/MAU)',
                    needsConfig: false,
                    className: 'row-span-2 h-[576px]',
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [dauSeries, wauSeries, mauSeries],
                            interval: 'day',
                            dateRange: {
                                date_from: '-90d',
                                explicitDate: false,
                            },
                            properties: [],
                            trendsFilter: {
                                display: ChartDisplayType.ActionsLineGraph,
                                showLegend: false,
                                yAxisScaleType: 'linear',
                                showValuesOnSeries: false,
                                smoothingIntervals: 1,
                                showPercentStackView: false,
                                aggregationAxisFormat: 'numeric',
                                showAlertThresholdLines: false,
                            },
                            breakdownFilter: {
                                breakdown_type: 'event',
                            },
                            filterTestAccounts: true,
                        },
                    },
                },
                {
                    name: 'Weekly Active Users',
                    needsConfig: false,
                    className: 'h-[284px]',
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [wauSeries],
                            interval: 'day',
                            dateRange: {
                                date_from: '-7d',
                                explicitDate: false,
                            },
                            properties: [],
                            trendsFilter: {
                                display: ChartDisplayType.BoldNumber,
                                showLegend: false,
                                yAxisScaleType: 'linear',
                                showValuesOnSeries: false,
                                smoothingIntervals: 1,
                                showPercentStackView: false,
                                aggregationAxisFormat: 'numeric',
                                showAlertThresholdLines: false,
                            },
                            compareFilter: {
                                compare: true,
                            },
                            breakdownFilter: {
                                breakdown_type: 'event',
                            },
                            filterTestAccounts: true,
                        },
                    },
                },
                {
                    name: 'Monthly Active Users',
                    needsConfig: false,
                    className: 'h-[284px]',
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [mauSeries],
                            interval: 'day',
                            dateRange: {
                                date_to: null,
                                date_from: '-30d',
                                explicitDate: false,
                            },
                            properties: [],
                            trendsFilter: {
                                display: ChartDisplayType.BoldNumber,
                                showLegend: false,
                                yAxisScaleType: 'linear',
                                showValuesOnSeries: false,
                                smoothingIntervals: 1,
                                showPercentStackView: false,
                                aggregationAxisFormat: 'numeric',
                                showAlertThresholdLines: false,
                            },
                            compareFilter: {
                                compare: true,
                            },
                            breakdownFilter: {
                                breakdown_type: 'event',
                            },
                            filterTestAccounts: true,
                        },
                    },
                },
            ],
        ],
    }),
    listeners(({ actions, values }) => ({
        saveActivityEvent: async () => {
            const filters = values.activityEventSelectionWithDefault
            // Convert FilterType to EventsNode[] using the conversion helper
            const activityEvents = actionsAndEventsToSeries(filters as any, true, MathAvailability.None)

            if (activityEvents.length > 0) {
                let currentTeam = values.currentTeam
                try {
                    // Get current team directly so that we have the most up to date extra_settings
                    currentTeam = await api.get('api/environments/@current')
                } catch {}

                const currentSettings = currentTeam?.extra_settings || {}
                const currentConfig = (currentSettings as any).customer_analytics_events || {}

                const extra_settings = {
                    ...currentSettings,
                    customer_analytics_events: {
                        ...currentConfig,
                        activity_event: activityEvents[0], // Take the first (and only) event
                    },
                }
                actions.updateCurrentTeam({
                    extra_settings,
                })
                actions.setActivityEventSelection(null as any)
            }
        },
        toggleEventConfigModal: ({ isOpen }) => {
            const isClosing = isOpen === false || (isOpen === undefined && values.isEventConfigModalOpen)
            if (isClosing) {
                actions.setActivityEventSelection(null as any)
            }
        },
    })),
])
