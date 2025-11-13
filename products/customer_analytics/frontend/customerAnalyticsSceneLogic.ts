import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
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
        tabId: [() => [(_, props: CustomerAnalyticsSceneLogicProps) => props.tabId], (tabIdProp) => tabIdProp],
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
            (activityEventSelection, activityEvent): FilterType => {
                return (
                    activityEventSelection ?? {
                        insight: InsightType.TRENDS,
                        events: [{ id: activityEvent, type: EntityTypes.EVENTS, order: 0 }],
                    }
                )
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
            (currentTeam) => currentTeam?.extra_settings?.customer_analytics_events || {},
        ],
        activityEvent: [
            (s) => [s.customerAnalyticsEvents],
            (customerAnalyticsEvents) => customerAnalyticsEvents?.activity_event || '$pageview',
        ],
        dauSeries: [
            (s) => [s.activityEvent],
            (activityEvent) => ({
                kind: NodeKind.EventsNode,
                math: 'dau',
                event: activityEvent || null,
                properties: [],
            }),
        ],
        wauSeries: [
            (s) => [s.activityEvent],
            (activityEvent) => ({
                kind: NodeKind.EventsNode,
                math: 'weekly_active',
                event: activityEvent || null,
                properties: [],
            }),
        ],
        mauSeries: [
            (s) => [s.activityEvent],
            (activityEvent) => ({
                kind: NodeKind.EventsNode,
                math: 'monthly_active',
                event: activityEvent || null,
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
        saveActivityEvent: async () => {
            const selectedEvent = values.activityEventSelectionWithDefault.events?.[0]?.id
            if (selectedEvent && typeof selectedEvent === 'string') {
                let currentTeam = values.currentTeam
                try {
                    // Get current team directly so that we have the most up to date extra_settings
                    currentTeam = await api.get('api/environments/@current')
                } catch {}

                const currentSettings = currentTeam?.extra_settings
                const extra_settings = {
                    ...currentSettings,
                    customer_analytics_events: {
                        ...currentSettings.customer_analytics_events,
                        activity_event: selectedEvent,
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
                actions.setActivityEventSelection(null)
            }
        },
    })),
])
