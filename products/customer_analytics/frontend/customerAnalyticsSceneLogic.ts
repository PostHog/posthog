import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { FunnelLayout } from 'lib/constants'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { capitalizeFirstLetter, getDefaultInterval, wordPluralize } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { ActionsNode, AnyEntityNode, EventsNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    Breadcrumb,
    BreakdownAttributionType,
    ChartDisplayType,
    FunnelConversionWindowTimeUnit,
    FunnelStepReference,
    FunnelVizType,
    GroupMathType,
    GroupTypeIndex,
    PropertyMathType,
    SimpleIntervalType,
    StepOrderValue,
} from '~/types'

import { customerAnalyticsConfigLogic } from './customerAnalyticsConfigLogic'
import type { customerAnalyticsSceneLogicType } from './customerAnalyticsSceneLogicType'

export type BusinessType = 'b2c' | 'b2b'

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

const getDefaultCustomerAnalyticsInterval = (dateFrom: string | null, dateTo: string | null): SimpleIntervalType => {
    const interval = getDefaultInterval(dateFrom, dateTo)
    return interval === 'day' ? 'day' : 'month'
}

const INITIAL_DATE_FROM = '-30d' as string | null
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL: SimpleIntervalType = getDefaultCustomerAnalyticsInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)
const INITIAL_DATE_FILTER = {
    dateFrom: INITIAL_DATE_FROM,
    dateTo: INITIAL_DATE_TO,
    interval: INITIAL_INTERVAL,
}

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}_customer_analytics__` }

const setQueryParams = (params: Record<string, string>): string => {
    const searchParams = { ...router.values.searchParams }
    const urlParams = new URLSearchParams(searchParams)
    Object.entries(params).forEach(([key, value]) => {
        urlParams.set(key, value)
    })

    const currentPath = router.values.location.pathname
    return `${currentPath}${urlParams.toString() ? '?' + urlParams.toString() : ''}`
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
            groupsModel,
            ['aggregationLabel', 'groupsEnabled', 'groupTypesRaw'],
        ],
    })),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setBusinessType: (businessType: BusinessType) => ({ businessType }),
        setSelectedGroupType: (selectedGroupType: number) => ({ selectedGroupType }),
    }),
    reducers(() => ({
        dateFilter: [
            INITIAL_DATE_FILTER,
            persistConfig,
            {
                setDates: (_, { dateTo, dateFrom }) => ({
                    dateTo,
                    dateFrom,
                    interval: getDefaultCustomerAnalyticsInterval(dateFrom, dateTo),
                }),
            },
        ],
        businessType: [
            'b2c' as BusinessType,
            persistConfig,
            {
                setBusinessType: (_, { businessType }) => businessType,
            },
        ],
        selectedGroupType: [
            0,
            persistConfig,
            {
                setSelectedGroupType: (_, { selectedGroupType }) => selectedGroupType,
            },
        ],
    })),
    selectors({
        tabId: [
            () => [(_, props: CustomerAnalyticsSceneLogicProps) => props.tabId],
            (tabIdProp: string): string => tabIdProp,
        ],
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
        customerLabel: [
            (s) => [s.aggregationLabel, s.businessType, s.selectedGroupType],
            (
                aggregationLabel: any,
                businessType: BusinessType,
                selectedGroupType: number
            ): { singular: string; plural: string } => {
                if (!aggregationLabel || typeof aggregationLabel !== 'function') {
                    return { singular: 'user', plural: 'users' }
                }
                if (businessType === 'b2c') {
                    return aggregationLabel(undefined, true)
                }
                return aggregationLabel(selectedGroupType)
            },
        ],
        dateRange: [
            (s) => [s.dateFilter],
            (dateFilter: {
                dateFrom: string | null
                dateTo: string | null
            }): { date_from: string | null; date_to: string | null } => ({
                date_from: dateFilter.dateFrom,
                date_to: dateFilter.dateTo,
            }),
        ],
        groupOptions: [
            (s) => [s.groupTypesRaw],
            (groupTypesRaw: any[]): { label: string; value: number }[] => {
                return groupTypesRaw.map((groupType) => ({
                    label: capitalizeFirstLetter(groupType.name_plural || wordPluralize(groupType.group_type)),
                    value: groupType.group_type_index,
                }))
            },
        ],
        dauSeries: [
            (s) => [s.activityEvent, s.businessType, s.selectedGroupType],
            (
                activityEvent: EventsNode | ActionsNode | null,
                businessType: BusinessType,
                selectedGroupType: GroupTypeIndex
            ): AnyEntityNode | null => {
                if (!activityEvent) {
                    return null
                }
                if (businessType === 'b2c') {
                    return {
                        ...activityEvent,
                        math: BaseMathType.UniqueUsers,
                    }
                }
                return {
                    ...activityEvent,
                    math: GroupMathType.UniqueGroup,
                    math_group_type_index: selectedGroupType,
                }
            },
        ],
        wauSeries: [
            (s) => [s.activityEvent, s.businessType, s.selectedGroupType],
            (
                activityEvent: EventsNode | ActionsNode | null,
                businessType: BusinessType,
                selectedGroupType: GroupTypeIndex
            ): AnyEntityNode | null => {
                if (!activityEvent) {
                    return null
                }
                if (businessType === 'b2b') {
                    return {
                        ...activityEvent,
                        math: BaseMathType.WeeklyActiveUsers,
                        math_group_type_index: selectedGroupType,
                    }
                }
                return {
                    ...activityEvent,
                    math: BaseMathType.WeeklyActiveUsers,
                }
            },
        ],
        mauSeries: [
            (s) => [s.activityEvent, s.businessType, s.selectedGroupType],
            (
                activityEvent: EventsNode | ActionsNode | null,
                businessType: BusinessType,
                selectedGroupType: GroupTypeIndex
            ): AnyEntityNode | null => {
                if (!activityEvent) {
                    return null
                }
                if (businessType === 'b2b') {
                    return {
                        ...activityEvent,
                        math: BaseMathType.MonthlyActiveUsers,
                        math_group_type_index: selectedGroupType,
                    }
                }
                return {
                    ...activityEvent,
                    math: BaseMathType.MonthlyActiveUsers,
                }
            },
        ],
        signupSeries: [
            (s) => [s.businessType, s.selectedGroupType, s.signupEvent],
            (businessType: BusinessType, selectedGroupType: GroupTypeIndex, signupEvent): AnyEntityNode | null => {
                if (Object.keys(signupEvent).length === 0) {
                    return null
                }
                if (businessType === 'b2c') {
                    return {
                        ...signupEvent,
                        math: BaseMathType.UniqueUsers,
                    }
                }
                return {
                    ...signupEvent,
                    math: GroupMathType.UniqueGroup,
                    math_group_type_index: selectedGroupType,
                }
            },
        ],
        signupPageviewSeries: [
            (s) => [s.businessType, s.selectedGroupType, s.signupPageviewEvent],
            (
                businessType: BusinessType,
                selectedGroupType: GroupTypeIndex,
                signupPageviewEvent
            ): AnyEntityNode | null => {
                if (Object.keys(signupPageviewEvent).length === 0) {
                    return null
                }
                if (businessType === 'b2c') {
                    return {
                        ...signupPageviewEvent,
                        math: BaseMathType.UniqueUsers,
                    }
                }
                return {
                    ...signupPageviewEvent,
                    math: GroupMathType.UniqueGroup,
                    math_group_type_index: selectedGroupType,
                }
            },
        ],
        subscriptionSeries: [
            (s) => [s.businessType, s.selectedGroupType, s.subscriptionEvent],
            (
                businessType: BusinessType,
                selectedGroupType: GroupTypeIndex,
                subscriptionEvent
            ): AnyEntityNode | null => {
                if (Object.keys(subscriptionEvent).length === 0) {
                    return null
                }
                if (businessType === 'b2c') {
                    return {
                        ...subscriptionEvent,
                        math: BaseMathType.UniqueUsers,
                    }
                }
                return {
                    ...subscriptionEvent,
                    math: GroupMathType.UniqueGroup,
                    math_group_type_index: selectedGroupType,
                }
            },
        ],
        paymentSeries: [
            (s) => [s.businessType, s.selectedGroupType, s.paymentEvent],
            (businessType: BusinessType, selectedGroupType: GroupTypeIndex, paymentEvent): AnyEntityNode | null => {
                if (Object.keys(paymentEvent).length === 0) {
                    return null
                }
                if (businessType === 'b2c') {
                    return {
                        ...paymentEvent,
                        math: BaseMathType.UniqueUsers,
                    }
                }
                return {
                    ...paymentEvent,
                    math: GroupMathType.UniqueGroup,
                    math_group_type_index: selectedGroupType,
                }
            },
        ],
        activeUsersInsights: [
            (s) => [s.customerLabel, s.dauSeries, s.wauSeries, s.mauSeries, s.dateRange],
            (
                customerLabel: Record<string, string>,
                dauSeries: AnyEntityNode | null,
                wauSeries: AnyEntityNode | null,
                mauSeries: AnyEntityNode | null,
                dateRange: { date_from: string | null; date_to: string | null }
            ): InsightDefinition[] => {
                // Backend guarantees activity event exists, but add safety check
                if (!dauSeries || !wauSeries || !mauSeries) {
                    return []
                }
                return [
                    {
                        name: `Active ${customerLabel.plural} (daily/weekly/monthly)`,
                        className: 'row-span-2 h-[576px]',
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [dauSeries, wauSeries, mauSeries],
                                interval: 'day',
                                dateRange: {
                                    date_from: dateRange.date_from,
                                    date_to: dateRange.date_to,
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
                        name: `Weekly active ${customerLabel.plural}`,
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
                        name: `Monthly active ${customerLabel.plural}`,
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
            (s) => [s.customerLabel],
            (customerLabel: { singular: string; plural: string }): InsightDefinition[] => [
                {
                    name: 'Unique sessions',
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
                    name: `Unique ${customerLabel.plural}`,
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
                    name: 'Average session duration',
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
            (s) => [
                s.businessType,
                s.customerLabel,
                s.signupSeries,
                s.paymentSeries,
                s.selectedGroupType,
                s.subscriptionSeries,
                s.signupPageviewSeries,
                s.dauSeries,
                s.dateRange,
            ],
            (
                businessType: BusinessType,
                customerLabel: { singular: string; plural: string },
                signupSeries: AnyEntityNode | null,
                paymentSeries: AnyEntityNode | null,
                selectedGroupType: number,
                subscriptionSeries: AnyEntityNode | null,
                signupPageviewSeries: AnyEntityNode | null,
                dauSeries: AnyEntityNode | null,
                dateRange: { date_from: string | null; date_to: string | null }
            ): InsightDefinition[] => [
                {
                    name: `${capitalizeFirstLetter(customerLabel.singular)} signups`,
                    requiredSeries: { signupSeries },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [signupSeries as AnyEntityNode],
                            interval: 'day',
                            dateRange: {
                                date_to: dateRange.date_to,
                                date_from: dateRange.date_from,
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
                    name: `Total paying ${customerLabel.plural}`,
                    requiredSeries: { paymentSeries },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [paymentSeries as AnyEntityNode],
                            interval: 'day',
                            dateRange: {
                                date_to: dateRange.date_to,
                                date_from: dateRange.date_from,
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
                    name: `${capitalizeFirstLetter(customerLabel.singular)} signups and subscriptions`,
                    requiredSeries: { signupSeries, subscriptionSeries },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [signupSeries as AnyEntityNode, subscriptionSeries as AnyEntityNode],
                            interval: 'day',
                            dateRange: {
                                date_from: dateRange.date_from,
                                date_to: dateRange.date_to,
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
                    name: 'New signups',
                    requiredSeries: { signupSeries },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [signupSeries as AnyEntityNode],
                            interval: 'week',
                            dateRange: {
                                date_to: dateRange.date_to,
                                date_from: dateRange.date_from,
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
                    name: 'Cumulative signups (adoption)',
                    requiredSeries: { signupSeries },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [signupSeries as AnyEntityNode],
                            interval: 'day',
                            dateRange: {
                                date_from: dateRange.date_from,
                                date_to: dateRange.date_to,
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
                    name: 'Signup conversion',
                    requiredSeries: { signupSeries, signupPageviewSeries },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.FunnelsQuery,
                            ...(businessType === 'b2c' ? {} : { aggregation_group_type_index: selectedGroupType }),
                            series: [signupPageviewSeries as AnyEntityNode, signupSeries as AnyEntityNode],
                            interval: 'week',
                            dateRange: {
                                date_from: dateRange.date_from,
                                date_to: dateRange.date_to,
                                explicitDate: false,
                            },
                            properties: [],
                            funnelsFilter: {
                                layout: FunnelLayout.horizontal,
                                exclusions: [],
                                funnelVizType: FunnelVizType.Steps,
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
                    name: `Which ${customerLabel.plural} are highly engaged?`,
                    requiredSeries: { dauSeries },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.LifecycleQuery,
                            ...(businessType === 'b2c' ? {} : { aggregation_group_type_index: selectedGroupType }),
                            series: [dauSeries as AnyEntityNode],
                            interval: 'week',
                            dateRange: {
                                date_from: dateRange.date_from,
                                date_to: dateRange.date_to,
                                explicitDate: false,
                            },
                            properties: [],
                            lifecycleFilter: {
                                showLegend: false,
                            },
                            filterTestAccounts: true,
                        },
                    },
                },
                {
                    name: 'Free-to-paid conversion',
                    requiredSeries: { signupSeries, paymentSeries },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.FunnelsQuery,
                            ...(businessType === 'b2c' ? {} : { aggregation_group_type_index: selectedGroupType }),
                            series: [signupSeries as AnyEntityNode, paymentSeries as AnyEntityNode],
                            dateRange: {
                                date_from: dateRange.date_from,
                                date_to: dateRange.date_to,
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
            ],
        ],
    }),
    tabAwareActionToUrl(() => ({
        setDates: ({ dateFrom, dateTo }): string =>
            setQueryParams({ date_from: dateFrom ?? '', date_to: dateTo ?? '' }),
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        '*': (_, { date_from, date_to }) => {
            if (
                (date_from && date_from !== values.dateFilter.dateFrom) ||
                (date_to && date_to !== values.dateFilter.dateTo)
            ) {
                actions.setDates(date_from, date_to)
            }
        },
    })),
])
