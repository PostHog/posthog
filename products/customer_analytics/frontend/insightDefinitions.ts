import { FunnelLayout } from 'lib/constants'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    BreakdownAttributionType,
    ChartDisplayType,
    FunnelConversionWindowTimeUnit,
    FunnelStepReference,
    FunnelVizType,
    PropertyMathType,
    StepOrderValue,
} from '~/types'

// Default placeholders for insights that need configuration
export const SIGNED_UP: any = {
    kind: NodeKind.EventsNode,
    event: null,
    properties: [],
}

export const SUBSCRIBED: any = {
    kind: NodeKind.EventsNode,
    event: null,
    properties: [],
}

export const SUB_PAID: any = {
    kind: NodeKind.EventsNode,
    event: null,
    properties: [],
}

export const ENGAGEMENT: any = {
    kind: NodeKind.EventsNode,
    event: null,
    properties: [],
}

export const VIEWED_SIGNUP: any = {
    kind: NodeKind.EventsNode,
    event: null,
    properties: [],
}

export const VISIT: any = {
    kind: NodeKind.EventsNode,
    event: null,
    properties: [],
}

export const VIEWED_PRICING: any = {
    kind: NodeKind.EventsNode,
    event: null,
    properties: [],
}

export const CLICKED_PRICING_CTA: any = {
    kind: NodeKind.EventsNode,
    event: null,
    properties: [],
}

export interface InsightDefinition {
    name: string
    description?: string
    query: InsightVizNode
    needsConfig?: boolean
    className?: string
}

export const CUSTOMER_ANALYTICS_ENGAGEMENT_AND_CONVERSION_INSIGHTS: InsightDefinition[] = [
    {
        name: 'Which customers are highly engaged?',
        description: 'Engagement event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.LifecycleQuery,
                series: [ENGAGEMENT],
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
        description: 'Subscribed event, Subscription paid event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.FunnelsQuery,
                series: [SIGNED_UP, SUB_PAID],
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

export const CUSTOMER_ANALYTICS_SESSION_INSIGHTS: InsightDefinition[] = [
    {
        name: 'Unique sessions (last 1h)',
        description: 'Events without session IDs are excluded.',
        needsConfig: false,
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
        needsConfig: false,
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
        needsConfig: false,
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
]

export const CUSTOMER_ANALYTICS_SIGNUP_AND_SUBS_INSIGHTS: InsightDefinition[] = [
    {
        name: 'User Signups',
        description: 'Signup event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [SIGNED_UP],
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
        description: 'Subscription paid event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [SUBSCRIBED],
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
        description: 'Signup event, Subscription event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [SIGNED_UP, SUBSCRIBED],
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
        description: 'Signup event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [SIGNED_UP],
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
        description: 'Signup event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [SIGNED_UP],
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
        description: 'Signup event, Signup page view event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.FunnelsQuery,
                series: [VIEWED_SIGNUP, SIGNED_UP],
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
        name: 'Acquisition Conversion',
        description: 'Website pageview event, Signup pageview event, Signup event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.FunnelsQuery,
                series: [VISIT, VIEWED_SIGNUP, SIGNED_UP],
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
    {
        name: 'What percentage of people on the signup page click the CTA?',
        description: 'Pricing pageview, Signup CTA click event',
        needsConfig: true,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.FunnelsQuery,
                series: [VIEWED_PRICING, CLICKED_PRICING_CTA],
                interval: 'week',
                dateRange: {
                    date_to: null,
                    date_from: '-180d',
                    explicitDate: false,
                },
                properties: [],
                funnelsFilter: {
                    layout: FunnelLayout.vertical,
                    exclusions: [],
                    funnelVizType: FunnelVizType.Trends,
                    funnelOrderType: StepOrderValue.ORDERED,
                    funnelStepReference: FunnelStepReference.total,
                    funnelWindowInterval: 2,
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
]
