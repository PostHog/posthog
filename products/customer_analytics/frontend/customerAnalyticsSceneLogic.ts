import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { Breadcrumb, ChartDisplayType, EntityTypes, FilterType, InsightType } from '~/types'

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
        setActiveEventSelection: (filters: FilterType) => ({
            filters,
        }),
        saveActiveEvent: true,
        toggleEventConfigModal: (isOpen?: boolean) => ({ isOpen }),
    }),
    reducers({
        activeEventSelection: [
            null as FilterType | null,
            {
                setActiveEventSelection: (_, { filters }) => filters,
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
        tabId: [() => [(_, props: CustomerAnalyticsSceneLogicProps) => props.tabId], (tabId) => tabId],
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
        activeEventSelectionWithDefault: [
            (s) => [s.activeEventSelection, s.activeEvent],
            (activeEventSelection, activeEvent): FilterType => {
                return (
                    activeEventSelection ?? {
                        insight: InsightType.TRENDS,
                        events: [{ id: activeEvent, type: EntityTypes.EVENTS, order: 0 }],
                    }
                )
            },
        ],
        hasActiveEventChanged: [
            (s) => [s.activeEventSelection],
            (activeEventSelection): boolean => {
                return activeEventSelection !== null
            },
        ],
        customerAnalyticsEvents: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.extra_settings?.customer_analytics_events || {},
        ],
        activeEvent: [
            (s) => [s.customerAnalyticsEvents],
            (customerAnalyticsEvents) => customerAnalyticsEvents?.active_event || '$pageview',
        ],
        dauSeries: [
            (s) => [s.activeEvent],
            (activeEvent) => ({
                kind: NodeKind.EventsNode,
                math: 'dau',
                event: activeEvent || null,
                properties: [],
            }),
        ],
        wauSeries: [
            (s) => [s.activeEvent],
            (activeEvent) => ({
                kind: NodeKind.EventsNode,
                math: 'weekly_active',
                event: activeEvent || null,
                properties: [],
            }),
        ],
        mauSeries: [
            (s) => [s.activeEvent],
            (activeEvent) => ({
                kind: NodeKind.EventsNode,
                math: 'monthly_active',
                event: activeEvent || null,
                properties: [],
            }),
        ],
        activeUsersInsights: [
            (s) => [s.dauSeries, s.wauSeries, s.mauSeries],
            (dauSeries, wauSeries, mauSeries) => [
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
        saveActiveEvent: () => {
            const selectedEvent = values.activeEventSelectionWithDefault.events?.[0]?.id
            if (selectedEvent && typeof selectedEvent === 'string') {
                actions.updateCurrentTeam({
                    extra_settings: {
                        customer_analytics_events: {
                            active_event: selectedEvent,
                        },
                    },
                })
                actions.setActiveEventSelection(null as any)
            }
        },
        toggleEventConfigModal: ({ isOpen }) => {
            const isClosing = isOpen === false || (isOpen === undefined && values.isEventConfigModalOpen)
            if (isClosing) {
                actions.setActiveEventSelection(null)
            }
        },
    })),
])
