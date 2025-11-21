import { connect, kea, path, selectors } from 'kea'

import { FunnelLayout } from 'lib/constants'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { ActionsNode, AnyEntityNode, EventsNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    Breadcrumb,
    BreakdownAttributionType,
    ChartDisplayType,
    FunnelConversionWindowTimeUnit,
    FunnelStepReference,
    FunnelVizType,
    PropertyMathType,
    StepOrderValue,
} from '~/types'

import { customerAnalyticsConfigLogic } from './customerAnalyticsConfigLogic'
import type { customerAnalyticsSceneLogicType } from './customerAnalyticsSceneLogicType'

export interface CustomerAnalyticsSceneLogicProps {
    tabId: string
}

export interface InsightDefinition {
    name: string
    description?: string
    query: InsightVizNode
    requiredSeries?: Record<string, AnyEntityNode | null>
    className?: string
}

export const customerAnalyticsSceneLogic = kea<customerAnalyticsSceneLogicType>([
    path(['scenes', 'customerAnalytics', 'customerAnalyticsScene']),
    tabAwareScene(),
    connect(() => ({
        values: [
            customerAnalyticsConfigLogic,
            [
                'customerAnalyticsConfig',
                'activityEvent',
                'signupEvent',
                'signupPageviewEvent',
                'subscriptionEvent',
                'paymentEvent',
            ],
        ],
    })),
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
        dauSeries: [
            (s) => [s.activityEvent],
            (activityEvent: EventsNode | ActionsNode | null): AnyEntityNode | null => {
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
            (activityEvent: EventsNode | ActionsNode | null): AnyEntityNode | null => {
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
            (activityEvent: EventsNode | ActionsNode | null): AnyEntityNode | null => {
                if (!activityEvent) {
                    return null
                }
                return {
                    ...activityEvent,
                    math: BaseMathType.MonthlyActiveUsers,
                }
            },
        ],
        signupSeries: [
            (s) => [s.signupEvent],
            (signupEvent): AnyEntityNode | null => {
                if (Object.keys(signupEvent).length === 0) {
                    return null
                }
                return {
                    ...signupEvent,
                    math: BaseMathType.UniqueUsers,
                }
            },
        ],
        signupPageviewSeries: [
            (s) => [s.signupPageviewEvent],
            (signupPageviewEvent): AnyEntityNode | null => {
                if (Object.keys(signupPageviewEvent).length === 0) {
                    return null
                }
                return {
                    ...signupPageviewEvent,
                    math: BaseMathType.UniqueUsers,
                }
            },
        ],
        subscriptionSeries: [
            (s) => [s.subscriptionEvent],
            (subscriptionEvent): AnyEntityNode | null => {
                if (Object.keys(subscriptionEvent).length === 0) {
                    return null
                }
                return {
                    ...subscriptionEvent,
                    math: BaseMathType.UniqueUsers,
                }
            },
        ],
        paymentSeries: [
            (s) => [s.paymentEvent],
            (paymentEvent): AnyEntityNode | null => {
                if (Object.keys(paymentEvent).length === 0) {
                    return null
                }
                return {
                    ...paymentEvent,
                    math: BaseMathType.UniqueUsers,
                }
            },
        ],
        activeUsersInsights: [
            (s) => [s.dauSeries, s.wauSeries, s.mauSeries],
            (
                dauSeries: AnyEntityNode | null,
                wauSeries: AnyEntityNode | null,
                mauSeries: AnyEntityNode | null
            ): InsightDefinition[] => {
                // Backend guarantees activity event exists, but add safety check
                if (!dauSeries || !wauSeries || !mauSeries) {
                    return []
                }
                return [
                    {
                        name: 'Active Users (DAU/WAU/MAU)',
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
        sessionInsights: [
            () => [],
            () => [
                {
                    name: 'Unique sessions (last 1h)',
                    description: 'Events without session IDs are excluded.',
                    className: 'h-[284px]',
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [
                                {
                                    kind: NodeKind.EventsNode,
                                    math: BaseMathType.UniqueSessions,
                                    name: 'All events',
                                    event: null,
                                },
                            ],
                            interval: 'minute',
                            dateRange: {
                                date_to: '',
                                date_from: '-1h',
                                explicitDate: false,
                            },
                            properties: [],
                            trendsFilter: {
                                display: ChartDisplayType.BoldNumber,
                                showLegend: false,
                                yAxisScaleType: 'linear',
                                showValuesOnSeries: false,
                                showPercentStackView: false,
                                aggregationAxisFormat: 'numeric',
                                showAlertThresholdLines: false,
                            },
                            compareFilter: {
                                compare: true,
                            },
                            breakdownFilter: undefined,
                            filterTestAccounts: true,
                        },
                    },
                },
                {
                    name: 'Unique users (last 1h)',
                    description: 'Number of unique users recently.',
                    className: 'h-[284px]',
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [
                                {
                                    kind: NodeKind.EventsNode,
                                    math: BaseMathType.UniqueUsers,
                                    name: 'All events',
                                    event: null,
                                },
                            ],
                            interval: 'hour',
                            dateRange: {
                                date_to: '',
                                date_from: '-1h',
                                explicitDate: false,
                            },
                            properties: [],
                            trendsFilter: {
                                display: ChartDisplayType.BoldNumber,
                                showLegend: false,
                                yAxisScaleType: 'linear',
                                showValuesOnSeries: false,
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
                    name: 'Average session duration (last 1h)',
                    description: 'Average session duration for recent sessions.',
                    className: 'h-[284px]',
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [
                                {
                                    kind: NodeKind.EventsNode,
                                    math: PropertyMathType.Average,
                                    name: '$pageview',
                                    event: '$pageview',
                                    math_property: '$session_duration',
                                },
                            ],
                            interval: 'minute',
                            dateRange: {
                                date_to: '',
                                date_from: '-1h',
                                explicitDate: false,
                            },
                            properties: [],
                            trendsFilter: {
                                display: ChartDisplayType.BoldNumber,
                                showLegend: false,
                                yAxisScaleType: 'linear',
                                showValuesOnSeries: false,
                                showPercentStackView: false,
                                aggregationAxisFormat: 'duration',
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
        signupInsights: [
            (s) => [s.signupSeries, s.paymentSeries, s.subscriptionSeries, s.signupPageviewSeries, s.dauSeries],
            (signupSeries, paymentSeries, subscriptionSeries, signupPageviewSeries, dauSeries): InsightDefinition[] => {
                return [
                    {
                        name: 'User Signups',
                        requiredSeries: { signupSeries },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [signupSeries as AnyEntityNode],
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
                    {
                        name: 'Total Paying Customers',
                        requiredSeries: { paymentSeries },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [paymentSeries as AnyEntityNode],
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
                                    showPercentStackView: false,
                                    aggregationAxisFormat: 'numeric',
                                    showAlertThresholdLines: false,
                                },
                                compareFilter: {
                                    compare: true,
                                },
                                filterTestAccounts: true,
                            },
                        },
                    },
                    {
                        name: 'User signups and subscriptions',
                        requiredSeries: { signupSeries, subscriptionSeries },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [signupSeries as AnyEntityNode, subscriptionSeries as AnyEntityNode],
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
                                    showMultipleYAxes: false,
                                    showValuesOnSeries: false,
                                    smoothingIntervals: 7,
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
                        name: 'New Signups (Weekly)',
                        requiredSeries: { signupSeries },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [signupSeries as AnyEntityNode],
                                interval: 'week',
                                dateRange: {
                                    date_to: null,
                                    date_from: '-180d',
                                    explicitDate: false,
                                },
                                properties: [],
                                trendsFilter: {
                                    display: ChartDisplayType.ActionsAreaGraph,
                                    showLegend: false,
                                    yAxisScaleType: 'linear',
                                    showValuesOnSeries: false,
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
                        name: 'Cumulative Signups (Adoption)',
                        requiredSeries: { signupSeries },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [signupSeries as AnyEntityNode],
                                interval: 'day',
                                dateRange: {
                                    date_from: '-90d',
                                    explicitDate: false,
                                },
                                properties: [],
                                trendsFilter: {
                                    display: ChartDisplayType.ActionsLineGraphCumulative,
                                    showLegend: false,
                                    showTrendLines: false,
                                    yAxisScaleType: 'linear',
                                    showMultipleYAxes: false,
                                    showValuesOnSeries: false,
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
                        name: 'Signup Conversion Rate',
                        requiredSeries: { signupSeries, signupPageviewSeries },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.FunnelsQuery,
                                series: [signupPageviewSeries as AnyEntityNode, signupSeries as AnyEntityNode],
                                interval: 'week',
                                dateRange: {
                                    date_from: '-30d',
                                    explicitDate: false,
                                },
                                properties: [],
                                funnelsFilter: {
                                    layout: FunnelLayout.vertical,
                                    exclusions: [],
                                    funnelVizType: FunnelVizType.Trends,
                                    funnelOrderType: StepOrderValue.ORDERED,
                                    funnelStepReference: FunnelStepReference.total,
                                    funnelWindowInterval: 14,
                                    breakdownAttributionType: BreakdownAttributionType.FirstTouch,
                                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                                },
                                breakdownFilter: {
                                    breakdown_type: 'event',
                                },
                                filterTestAccounts: true,
                            },
                        },
                    },
                    {
                        name: 'Which customers are highly engaged?',
                        requiredSeries: { dauSeries },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.LifecycleQuery,
                                series: [dauSeries as AnyEntityNode],
                                interval: 'week',
                                dateRange: {
                                    date_from: '-30d',
                                    explicitDate: false,
                                },
                                properties: [],
                                lifecycleFilter: {
                                    showLegend: false,
                                },
                                filterTestAccounts: true,
                                aggregation_group_type_index: 0,
                            },
                        },
                    },
                    {
                        name: 'Free to Paid User Conversion',
                        requiredSeries: { signupSeries, paymentSeries },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.FunnelsQuery,
                                series: [signupSeries as AnyEntityNode, paymentSeries as AnyEntityNode],
                                dateRange: {
                                    date_from: '-90d',
                                    explicitDate: false,
                                },
                                properties: [],
                                funnelsFilter: {
                                    layout: FunnelLayout.horizontal,
                                    exclusions: [],
                                    funnelVizType: FunnelVizType.Steps,
                                    funnelOrderType: StepOrderValue.ORDERED,
                                    funnelStepReference: FunnelStepReference.total,
                                    funnelWindowInterval: 6,
                                    breakdownAttributionType: BreakdownAttributionType.FirstTouch,
                                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Week,
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
    }),
])
