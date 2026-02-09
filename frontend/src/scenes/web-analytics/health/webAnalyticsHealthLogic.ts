import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { isDefinitionStale } from 'lib/utils/definitions'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EventDefinitionType, TeamType } from '~/types'

import {
    HealthCheck,
    HealthCheckCategory,
    HealthCheckId,
    HealthCheckStatus,
    OverallHealthStatus,
} from './healthCheckTypes'
import type { webAnalyticsHealthLogicType } from './webAnalyticsHealthLogicType'

export interface WebAnalyticsHealthStatus {
    isSendingWebVitals: boolean
    isSendingPageViews: boolean
    isSendingPageLeaves: boolean
    isSendingPageLeavesScroll: boolean
}

export const webAnalyticsHealthLogic = kea<webAnalyticsHealthLogicType>([
    path(['scenes', 'web-analytics', 'health', 'webAnalyticsHealthLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeam'], reverseProxyCheckerLogic, ['hasReverseProxy', 'hasReverseProxyLoading']],
        actions: [
            teamLogic,
            ['updateCurrentTeam'],
            reverseProxyCheckerLogic,
            ['loadHasReverseProxy'],
            eventUsageLogic,
            [
                'reportWebAnalyticsHealthStatus',
                'reportWebAnalyticsHealthTabViewed',
                'reportWebAnalyticsHealthSectionToggled',
                'reportWebAnalyticsHealthActionClicked',
                'reportWebAnalyticsHealthRefreshed',
            ],
        ],
    })),

    actions({
        refreshHealthChecks: true,
        trackTabViewed: true,
        trackSectionToggled: (category: HealthCheckCategory, isExpanded: boolean) => ({ category, isExpanded }),
        trackActionClicked: (
            checkId: HealthCheckId,
            category: HealthCheckCategory,
            status: HealthCheckStatus,
            isUrgent: boolean
        ) => ({
            checkId,
            category,
            status,
            isUrgent,
        }),
    }),

    loaders(({}) => ({
        webAnalyticsHealthStatus: {
            __default: null as WebAnalyticsHealthStatus | null,
            loadWebAnalyticsHealthStatus: async (): Promise<WebAnalyticsHealthStatus> => {
                const [webVitalsResult, pageviewResult, pageleaveResult, pageleaveScroll] = await Promise.allSettled([
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$web_vitals',
                    }),
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$pageview',
                    }),
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$pageleave',
                    }),
                    api.propertyDefinitions.list({
                        event_names: ['$pageleave'],
                        properties: ['$prev_pageview_max_content_percentage'],
                    }),
                ])

                // no need to worry about pagination here, event names beginning with $ are reserved, and we're not
                // going to add enough reserved event names that match this search term to cause problems
                const webVitalsEntry =
                    webVitalsResult.status === 'fulfilled'
                        ? webVitalsResult.value.results.find((r) => r.name === '$web_vitals')
                        : undefined

                const pageviewEntry =
                    pageviewResult.status === 'fulfilled'
                        ? pageviewResult.value.results.find((r) => r.name === '$pageview')
                        : undefined

                const pageleaveEntry =
                    pageleaveResult.status === 'fulfilled'
                        ? pageleaveResult.value.results.find((r) => r.name === '$pageleave')
                        : undefined

                const pageleaveScrollEntry =
                    pageleaveScroll.status === 'fulfilled'
                        ? pageleaveScroll.value.results.find((r) => r.name === '$prev_pageview_max_content_percentage')
                        : undefined

                return {
                    isSendingWebVitals: !!webVitalsEntry && !isDefinitionStale(webVitalsEntry),
                    isSendingPageViews: !!pageviewEntry && !isDefinitionStale(pageviewEntry),
                    isSendingPageLeaves: !!pageleaveEntry && !isDefinitionStale(pageleaveEntry),
                    isSendingPageLeavesScroll: !!pageleaveScrollEntry && !isDefinitionStale(pageleaveScrollEntry),
                }
            },
        },
    })),

    selectors({
        eventChecks: [
            (s) => [s.webAnalyticsHealthStatus, s.webAnalyticsHealthStatusLoading],
            (webAnalyticsHealthStatus: WebAnalyticsHealthStatus | null, loading: boolean): HealthCheck[] => {
                if (loading || !webAnalyticsHealthStatus) {
                    return [
                        createLoadingCheck(HealthCheckId.PAGEVIEW_EVENTS, 'events', 'PageView events'),
                        createLoadingCheck(HealthCheckId.PAGELEAVE_EVENTS, 'events', 'PageLeave events'),
                        createLoadingCheck(HealthCheckId.SCROLL_DEPTH, 'events', 'Scroll depth tracking'),
                    ]
                }

                return [
                    {
                        id: HealthCheckId.PAGEVIEW_EVENTS,
                        category: 'events',
                        title: '$pageview',
                        description: webAnalyticsHealthStatus.isSendingPageViews
                            ? 'Events are flowing in as expected. Head over to the Web Analytics tab to start reviewing your analytics!'
                            : 'Complete the PostHog installation to start seeing events in your dashboard.',
                        status: webAnalyticsHealthStatus.isSendingPageViews ? 'success' : 'error',
                        action: webAnalyticsHealthStatus.isSendingPageViews
                            ? undefined
                            : {
                                  label: 'View installation guide',
                                  to: 'https://posthog.com/docs/libraries/js',
                              },
                        docsUrl: 'https://posthog.com/docs/product-analytics/capture-events',
                        urgent: true,
                    },
                    {
                        id: HealthCheckId.PAGELEAVE_EVENTS,
                        category: 'events',
                        title: '$pageleave',
                        description: webAnalyticsHealthStatus.isSendingPageLeaves
                            ? 'Bounce rate and session duration are accurate!'
                            : 'Without $pageleave events, bounce rate and session duration might be inaccurate.',
                        status: webAnalyticsHealthStatus.isSendingPageLeaves ? 'success' : 'warning',
                        action: webAnalyticsHealthStatus.isSendingPageLeaves
                            ? undefined
                            : {
                                  label: 'View installation guide',
                                  to: 'https://posthog.com/docs/libraries/js',
                              },
                        docsUrl: 'https://posthog.com/docs/web-analytics/dashboard#bounce-rate',
                    },
                    {
                        id: HealthCheckId.SCROLL_DEPTH,
                        category: 'events',
                        title: 'Scroll depth',
                        description: webAnalyticsHealthStatus.isSendingPageLeavesScroll
                            ? 'Scroll tracking is enabled! Tracking how far users scroll on each page.'
                            : 'Enable scroll depth to see how far users read your content before leaving.',
                        status: webAnalyticsHealthStatus.isSendingPageLeavesScroll ? 'success' : 'warning',
                        action: webAnalyticsHealthStatus.isSendingPageLeavesScroll
                            ? undefined
                            : {
                                  label: 'View installation guide',
                                  to: 'https://posthog.com/docs/libraries/js',
                              },
                        docsUrl: 'https://posthog.com/docs/web-analytics/scroll-depth',
                    },
                ]
            },
        ],

        configurationChecks: [
            (s) => [s.currentTeam, s.hasReverseProxy, s.hasReverseProxyLoading, s.hasAuthorizedUrls],
            (
                currentTeam: TeamType | null,
                hasReverseProxy: boolean | null,
                hasReverseProxyLoading: boolean,
                hasAuthorizedUrls: boolean
            ): HealthCheck[] => {
                const reverseProxyCheck: HealthCheck = hasReverseProxyLoading
                    ? createLoadingCheck(HealthCheckId.REVERSE_PROXY, 'configuration', 'Reverse proxy')
                    : {
                          id: HealthCheckId.REVERSE_PROXY,
                          category: 'configuration',
                          title: 'Reverse proxy',
                          description: hasReverseProxy
                              ? 'Reverse proxy is configured! Your tracking requests are routed through your own domain.'
                              : 'A reverse proxy routes PostHog requests through your own domain and helps prevent ad blockers from blocking tracking. Some metrics may not be accurate until this is configured.',
                          status: hasReverseProxy ? 'success' : 'warning',
                          action: hasReverseProxy
                              ? undefined
                              : {
                                    label: 'Set up reverse proxy',
                                    to: 'https://posthog.com/docs/advanced/proxy',
                                },
                          docsUrl: 'https://posthog.com/docs/advanced/proxy',
                          urgent: true,
                      }

                return [
                    {
                        id: HealthCheckId.AUTHORIZED_URLS,
                        category: 'configuration',
                        title: 'Authorized URLs',
                        description: hasAuthorizedUrls
                            ? `${currentTeam?.app_urls?.length} domain${(currentTeam?.app_urls?.length ?? 0) > 1 ? 's' : ''} configured. Your analytics are filtered to only include traffic from your domains.`
                            : "No authorized URLs configured. Some filters won't work correctly until you let us know what domains you are sending events from.",
                        status: hasAuthorizedUrls ? 'success' : 'warning',
                        action: hasAuthorizedUrls
                            ? { label: 'Manage domains', to: urls.settings('environment-web-analytics') }
                            : { label: 'Add domains', to: urls.settings('environment-web-analytics') },
                        docsUrl: 'https://posthog.com/docs/web-analytics/authorized-urls',
                    },
                    reverseProxyCheck,
                ]
            },
        ],

        performanceChecks: [
            (s) => [s.webAnalyticsHealthStatus, s.webAnalyticsHealthStatusLoading, s.currentTeam],
            (
                webAnalyticsHealthStatus: WebAnalyticsHealthStatus | null,
                loading: boolean,
                currentTeam: TeamType | null
            ): HealthCheck[] => {
                if (loading || !webAnalyticsHealthStatus) {
                    return [createLoadingCheck(HealthCheckId.WEB_VITALS, 'performance', 'Web vitals')]
                }

                const webVitalsEnabled = currentTeam?.autocapture_web_vitals_opt_in ?? false

                return [
                    {
                        id: HealthCheckId.WEB_VITALS,
                        category: 'performance',
                        title: '$web_vitals',
                        description: webAnalyticsHealthStatus.isSendingWebVitals
                            ? 'LCP, INP, and CLS are being tracked. You can monitor your real user experience!'
                            : webVitalsEnabled
                              ? 'Enabled but no data yet. Core Web Vitals (LCP, INP, CLS) measure real user experience.'
                              : 'Core Web Vitals (LCP, INP, CLS) measure real user experience. Google uses these metrics for search ranking.',
                        status: webAnalyticsHealthStatus.isSendingWebVitals ? 'success' : 'warning',
                        action:
                            webAnalyticsHealthStatus.isSendingWebVitals || webVitalsEnabled
                                ? { label: 'View Web Vitals', to: '/web/web-vitals' }
                                : { label: 'Enable Web Vitals', to: urls.settings('environment-web-analytics') },
                        docsUrl: 'https://posthog.com/docs/web-analytics/web-vitals',
                    },
                ]
            },
        ],

        allChecks: [
            (s) => [s.eventChecks, s.configurationChecks, s.performanceChecks],
            (
                eventChecks: HealthCheck[],
                configurationChecks: HealthCheck[],
                performanceChecks: HealthCheck[]
            ): HealthCheck[] => {
                return [...eventChecks, ...configurationChecks, ...performanceChecks]
            },
        ],

        checksByCategory: [
            (s) => [s.eventChecks, s.configurationChecks, s.performanceChecks],
            (eventChecks: HealthCheck[], configurationChecks: HealthCheck[], performanceChecks: HealthCheck[]) => ({
                events: eventChecks,
                configuration: configurationChecks,
                performance: performanceChecks,
            }),
        ],

        overallHealthStatus: [
            (s) => [s.allChecks],
            (allChecks: HealthCheck[]): OverallHealthStatus => {
                const passedCount = allChecks.filter((check) => check.status === 'success').length
                const warningCount = allChecks.filter((check) => check.status === 'warning').length
                const errorCount = allChecks.filter((check) => check.status === 'error').length
                const loadingCount = allChecks.filter((check) => check.status === 'loading').length
                const totalCount = allChecks.length

                let status: HealthCheckStatus
                let summary: string

                if (loadingCount > 0) {
                    status = 'loading'
                    summary = 'Checking your setup...'
                } else if (warningCount > 0 || errorCount > 0) {
                    status = 'warning'
                    const totalErrors = warningCount + errorCount
                    summary = `${totalErrors} recommendation${totalErrors > 1 ? 's' : ''} to improve your setup`
                } else {
                    status = 'success'
                    summary = 'Your web analytics setup looks great!'
                }

                return {
                    status,
                    summary,
                    passedCount,
                    warningCount,
                    errorCount,
                    totalCount,
                }
            },
        ],

        hasIssues: [
            (s) => [s.overallHealthStatus],
            (overallHealthStatus: OverallHealthStatus): boolean => {
                return overallHealthStatus.status === 'error' || overallHealthStatus.status === 'warning'
            },
        ],

        urgentFailedChecks: [
            (s) => [s.allChecks],
            (allChecks: HealthCheck[]): HealthCheck[] => {
                return allChecks.filter(
                    (check) => check.urgent && check.status !== 'success' && check.status !== 'loading'
                )
            },
        ],

        hasUrgentIssues: [
            (s) => [s.urgentFailedChecks],
            (urgentFailedChecks: HealthCheck[]): boolean => {
                return urgentFailedChecks.length > 0
            },
        ],

        hasAuthorizedUrls: [
            (s) => [s.currentTeam],
            (currentTeam: TeamType | null): boolean => {
                return !!currentTeam?.app_urls && currentTeam.app_urls.length > 0
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        refreshHealthChecks: () => {
            const { overallHealthStatus } = values
            actions.reportWebAnalyticsHealthRefreshed({
                overall_status: overallHealthStatus.status,
                passed_count: overallHealthStatus.passedCount,
            })
            actions.loadWebAnalyticsHealthStatus()
            actions.loadHasReverseProxy()
        },
        loadWebAnalyticsHealthStatusSuccess: () => {
            const { webAnalyticsHealthStatus, hasAuthorizedUrls, hasReverseProxy, overallHealthStatus } = values
            if (webAnalyticsHealthStatus && overallHealthStatus.status !== 'loading') {
                actions.reportWebAnalyticsHealthStatus({
                    has_pageviews: webAnalyticsHealthStatus.isSendingPageViews,
                    has_pageleaves: webAnalyticsHealthStatus.isSendingPageLeaves,
                    has_scroll_depth: webAnalyticsHealthStatus.isSendingPageLeavesScroll,
                    has_web_vitals: webAnalyticsHealthStatus.isSendingWebVitals,
                    has_authorized_urls: hasAuthorizedUrls,
                    has_reverse_proxy: hasReverseProxy ?? false,
                    overall_status: overallHealthStatus.status,
                })
            }
        },
        trackTabViewed: () => {
            const { overallHealthStatus } = values
            actions.reportWebAnalyticsHealthTabViewed({
                overall_status: overallHealthStatus.status,
                passed_count: overallHealthStatus.passedCount,
                warning_count: overallHealthStatus.warningCount,
                error_count: overallHealthStatus.errorCount,
            })
        },
        trackSectionToggled: ({ category, isExpanded }) => {
            actions.reportWebAnalyticsHealthSectionToggled({
                category,
                is_expanded: isExpanded,
            })
        },
        trackActionClicked: ({ checkId, category, status, isUrgent }) => {
            actions.reportWebAnalyticsHealthActionClicked({
                check_id: checkId,
                category,
                status,
                is_urgent: isUrgent,
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadWebAnalyticsHealthStatus()
    }),
])

function createLoadingCheck(id: HealthCheckId, category: HealthCheckCategory, title: string): HealthCheck {
    return {
        id,
        category,
        title,
        description: 'Checking...',
        status: 'loading',
    }
}
