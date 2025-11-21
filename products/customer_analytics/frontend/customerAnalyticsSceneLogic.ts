import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ActionsNode, EventsNode, NodeKind } from '~/queries/schema/schema-general'
import { isDataWarehouseNode } from '~/queries/utils'
import { BaseMathType, Breadcrumb, ChartDisplayType, FilterType, InsightType } from '~/types'

import { customerAnalyticsConfigLogic } from './customerAnalyticsConfigLogic'
import type { customerAnalyticsSceneLogicType } from './customerAnalyticsSceneLogicType'
import { InsightDefinition } from './insightDefinitions'

export interface CustomerAnalyticsSceneLogicProps {
    tabId: string
}

export const customerAnalyticsSceneLogic = kea<customerAnalyticsSceneLogicType>([
    path(['scenes', 'customerAnalytics', 'customerAnalyticsScene']),
    tabAwareScene(),
    connect(() => ({
        values: [customerAnalyticsConfigLogic, ['customerAnalyticsConfig', 'activityEvent']],
        actions: [customerAnalyticsConfigLogic, ['updateActivityEvent']],
    })),
    actions({
        setActivityEventSelection: (filters: FilterType | null) => ({
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
        hasActivityEventChanged: [
            (s) => [s.activityEventSelection],
            (activityEventSelection): boolean => {
                return activityEventSelection !== null
            },
        ],
        dauSeries: [
            (s) => [s.activityEvent],
            (activityEvent: EventsNode | ActionsNode | null): EventsNode | ActionsNode | null => {
                if (!activityEvent) {
                    return null
                }
                return {
                    ...activityEvent,
                    math: BaseMathType.UniqueUsers,
                }
            },
        ],
        wauSeries: [
            (s) => [s.activityEvent],
            (activityEvent: EventsNode | ActionsNode | null): EventsNode | ActionsNode | null => {
                if (!activityEvent) {
                    return null
                }
                return {
                    ...activityEvent,
                    math: BaseMathType.WeeklyActiveUsers,
                }
            },
        ],
        mauSeries: [
            (s) => [s.activityEvent],
            (activityEvent: EventsNode | ActionsNode | null): EventsNode | ActionsNode | null => {
                if (!activityEvent) {
                    return null
                }
                return {
                    ...activityEvent,
                    math: BaseMathType.MonthlyActiveUsers,
                }
            },
        ],
        activeUsersInsights: [
            (s) => [s.dauSeries, s.wauSeries, s.mauSeries],
            (
                dauSeries: EventsNode | ActionsNode | null,
                wauSeries: EventsNode | ActionsNode | null,
                mauSeries: EventsNode | ActionsNode | null
            ): InsightDefinition[] => {
                // Backend guarantees activity event exists, but add safety check
                if (!dauSeries || !wauSeries || !mauSeries) {
                    return []
                }
                return [
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
                ]
            },
        ],
        activityEventFilters: [
            (s) => [s.activityEvent, s.activityEventSelection],
            (activityEvent, activityEventSelection): FilterType => {
                if (activityEventSelection) {
                    return activityEventSelection
                }
                return {
                    insight: InsightType.TRENDS,
                    ...seriesToActionsAndEvents(activityEvent ? [activityEvent] : []),
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        saveActivityEvent: () => {
            const filters = values.activityEventSelection
            const activityEvents = actionsAndEventsToSeries(filters as any, true, MathAvailability.None)

            if (activityEvents.length > 0 && !isDataWarehouseNode(activityEvents[0])) {
                actions.updateActivityEvent(activityEvents[0])
                actions.setActivityEventSelection(null)
            }
        },
        toggleEventConfigModal: ({ isOpen }) => {
            const isClosing = isOpen === false || (isOpen === undefined && values.isEventConfigModalOpen)
            if (isClosing) {
                actions.setActivityEventSelection(null)
            }
        },
    })),
])
