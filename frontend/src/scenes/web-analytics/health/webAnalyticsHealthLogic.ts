import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import type { HealthIssuesResponse } from 'scenes/health/healthSceneLogic'
import {
    REFRESH_COOLDOWN_MS,
    REFRESH_POLL_COUNT,
    REFRESH_POLL_INTERVAL_MS,
    type HealthIssue,
} from 'scenes/health/types'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { TeamType } from '~/types'

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

const KIND_FOR_CHECK: Record<HealthCheckId, string> = {
    [HealthCheckId.PAGEVIEW_EVENTS]: 'no_live_events',
    [HealthCheckId.PAGELEAVE_EVENTS]: 'no_pageleave_events',
    [HealthCheckId.SCROLL_DEPTH]: 'scroll_depth',
    [HealthCheckId.AUTHORIZED_URLS]: 'authorized_urls',
    [HealthCheckId.REVERSE_PROXY]: 'reverse_proxy',
    [HealthCheckId.WEB_VITALS]: 'web_vitals',
}

function severityToStatus(severity: HealthIssue['severity']): HealthCheckStatus {
    return severity === 'critical' ? 'error' : 'warning'
}

function statusForCheck(checkId: HealthCheckId, issuesByKind: Record<string, HealthIssue>): HealthCheckStatus {
    const issue = issuesByKind[KIND_FOR_CHECK[checkId]]
    return issue ? severityToStatus(issue.severity) : 'success'
}

export const webAnalyticsHealthLogic = kea<webAnalyticsHealthLogicType>([
    path(['scenes', 'web-analytics', 'health', 'webAnalyticsHealthLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamId']],
        actions: [
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
        refreshHealthChecks: (isManual: boolean = true) => ({ isManual }),
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
        setNextRefreshAvailableAt: (timestamp: number | null) => ({ timestamp }),
    }),

    reducers({
        nextRefreshAvailableAt: [
            null as number | null,
            { persist: true },
            {
                setNextRefreshAvailableAt: (_, { timestamp }) => timestamp,
            },
        ],
    }),

    loaders(({ values }) => ({
        healthIssues: {
            __default: null as HealthIssuesResponse | null,
            loadHealthIssues: async (): Promise<HealthIssuesResponse | null> => {
                if (!values.currentTeamId) {
                    return null
                }
                const url = `api/environments/${values.currentTeamId}/health_issues/?status=active&dismissed=false`
                return await api.get(url)
            },
        },
    })),

    selectors({
        issuesByKind: [
            (s) => [s.healthIssues],
            (healthIssues: HealthIssuesResponse | null): Record<string, HealthIssue> => {
                const byKind: Record<string, HealthIssue> = {}
                for (const issue of healthIssues?.results ?? []) {
                    byKind[issue.kind] ??= issue
                }
                return byKind
            },
        ],

        webAnalyticsHealthStatus: [
            (s) => [s.healthIssues, s.issuesByKind],
            (
                healthIssues: HealthIssuesResponse | null,
                issuesByKind: Record<string, HealthIssue>
            ): WebAnalyticsHealthStatus | null => {
                if (healthIssues === null) {
                    return null
                }
                return {
                    isSendingWebVitals: !issuesByKind.web_vitals,
                    isSendingPageViews: !issuesByKind.no_live_events,
                    isSendingPageLeaves: !issuesByKind.no_pageleave_events,
                    isSendingPageLeavesScroll: !issuesByKind.scroll_depth,
                }
            },
        ],

        isInitialLoad: [
            (s) => [s.healthIssues, s.healthIssuesLoading],
            (healthIssues: HealthIssuesResponse | null, loading: boolean): boolean => loading && healthIssues === null,
        ],

        eventChecks: [
            (s) => [s.issuesByKind, s.isInitialLoad],
            (issuesByKind: Record<string, HealthIssue>, isInitialLoad: boolean): HealthCheck[] => {
                if (isInitialLoad) {
                    return [
                        createLoadingCheck(HealthCheckId.PAGEVIEW_EVENTS, 'events', 'PageView events'),
                        createLoadingCheck(HealthCheckId.PAGELEAVE_EVENTS, 'events', 'PageLeave events'),
                        createLoadingCheck(HealthCheckId.SCROLL_DEPTH, 'events', 'Scroll depth tracking'),
                    ]
                }

                const pageviewOk = statusForCheck(HealthCheckId.PAGEVIEW_EVENTS, issuesByKind) === 'success'
                const pageleaveOk = statusForCheck(HealthCheckId.PAGELEAVE_EVENTS, issuesByKind) === 'success'
                const scrollOk = statusForCheck(HealthCheckId.SCROLL_DEPTH, issuesByKind) === 'success'

                return [
                    {
                        id: HealthCheckId.PAGEVIEW_EVENTS,
                        category: 'events',
                        title: '$pageview',
                        description: pageviewOk
                            ? 'Events are flowing in as expected. Head over to the Web Analytics tab to start reviewing your analytics!'
                            : 'Complete the PostHog installation to start seeing events in your dashboard.',
                        status: statusForCheck(HealthCheckId.PAGEVIEW_EVENTS, issuesByKind),
                        action: pageviewOk
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
                        description: pageleaveOk
                            ? 'Bounce rate and session duration are accurate!'
                            : 'Without $pageleave events, bounce rate and session duration might be inaccurate.',
                        status: statusForCheck(HealthCheckId.PAGELEAVE_EVENTS, issuesByKind),
                        action: pageleaveOk
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
                        description: scrollOk
                            ? 'Scroll tracking is enabled! Tracking how far users scroll on each page.'
                            : 'Enable scroll depth to see how far users read your content before leaving.',
                        status: statusForCheck(HealthCheckId.SCROLL_DEPTH, issuesByKind),
                        action: scrollOk
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
            (s) => [s.currentTeam, s.issuesByKind, s.isInitialLoad, s.hasAuthorizedUrls],
            (
                currentTeam: TeamType | null,
                issuesByKind: Record<string, HealthIssue>,
                isInitialLoad: boolean,
                hasAuthorizedUrls: boolean
            ): HealthCheck[] => {
                const hasReverseProxy = statusForCheck(HealthCheckId.REVERSE_PROXY, issuesByKind) === 'success'
                const reverseProxyCheck: HealthCheck = isInitialLoad
                    ? createLoadingCheck(HealthCheckId.REVERSE_PROXY, 'configuration', 'Reverse proxy')
                    : {
                          id: HealthCheckId.REVERSE_PROXY,
                          category: 'configuration',
                          title: 'Reverse proxy',
                          description: hasReverseProxy
                              ? 'Reverse proxy is configured! Your tracking requests are routed through your own domain.'
                              : 'A reverse proxy routes PostHog requests through your own domain and helps prevent ad blockers from blocking tracking. Some metrics may not be accurate until this is configured.',
                          status: statusForCheck(HealthCheckId.REVERSE_PROXY, issuesByKind),
                          action: hasReverseProxy
                              ? undefined
                              : {
                                    label: 'Set up reverse proxy',
                                    to: urls.settings('organization-proxy'),
                                },
                          docsUrl: 'https://posthog.com/docs/advanced/proxy',
                          urgent: true,
                      }

                const authorizedUrlsCheck: HealthCheck = isInitialLoad
                    ? createLoadingCheck(HealthCheckId.AUTHORIZED_URLS, 'configuration', 'Authorized URLs')
                    : {
                          id: HealthCheckId.AUTHORIZED_URLS,
                          category: 'configuration',
                          title: 'Authorized URLs',
                          description: hasAuthorizedUrls
                              ? `${currentTeam?.app_urls?.length} domain${(currentTeam?.app_urls?.length ?? 0) > 1 ? 's' : ''} configured. Your analytics are filtered to only include traffic from your domains.`
                              : "No authorized URLs configured. Some filters won't work correctly until you let us know what domains you are sending events from.",
                          status: statusForCheck(HealthCheckId.AUTHORIZED_URLS, issuesByKind),
                          action: hasAuthorizedUrls
                              ? { label: 'Manage domains', to: urls.settings('environment-web-analytics') }
                              : { label: 'Add domains', to: urls.settings('environment-web-analytics') },
                      }

                return [authorizedUrlsCheck, reverseProxyCheck]
            },
        ],

        performanceChecks: [
            (s) => [s.issuesByKind, s.isInitialLoad, s.currentTeam],
            (
                issuesByKind: Record<string, HealthIssue>,
                isInitialLoad: boolean,
                currentTeam: TeamType | null
            ): HealthCheck[] => {
                if (isInitialLoad) {
                    return [createLoadingCheck(HealthCheckId.WEB_VITALS, 'performance', 'Web vitals')]
                }

                const isSendingWebVitals = statusForCheck(HealthCheckId.WEB_VITALS, issuesByKind) === 'success'
                const webVitalsEnabled = currentTeam?.autocapture_web_vitals_opt_in ?? false

                return [
                    {
                        id: HealthCheckId.WEB_VITALS,
                        category: 'performance',
                        title: '$web_vitals',
                        description: isSendingWebVitals
                            ? 'LCP, INP, and CLS are being tracked. You can monitor your real user experience!'
                            : webVitalsEnabled
                              ? 'Enabled but no data yet. Core Web Vitals (LCP, INP, CLS) measure real user experience.'
                              : 'Core Web Vitals (LCP, INP, CLS) measure real user experience. Google uses these metrics for search ranking.',
                        status: statusForCheck(HealthCheckId.WEB_VITALS, issuesByKind),
                        action:
                            isSendingWebVitals || webVitalsEnabled
                                ? { label: 'View Web Vitals', to: '/web/web-vitals' }
                                : {
                                      label: 'Enable Web Vitals',
                                      to: urls.settings('environment-web-analytics', 'web-vitals-autocapture'),
                                  },
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
            (s) => [s.issuesByKind],
            (issuesByKind: Record<string, HealthIssue>): boolean => !issuesByKind.authorized_urls,
        ],
    }),

    listeners(({ actions, values }) => ({
        refreshHealthChecks: async ({ isManual }, breakpoint) => {
            const { overallHealthStatus } = values
            actions.reportWebAnalyticsHealthRefreshed({
                overall_status: overallHealthStatus.status,
                passed_count: overallHealthStatus.passedCount,
            })

            const url = `api/environments/${values.currentTeamId}/health_issues/refresh/`
            try {
                const response = await api.create<{
                    scheduled_kinds: string[]
                    kinds_failed: string[]
                    team_id: number
                }>(url)
                breakpoint()

                actions.setNextRefreshAvailableAt(Date.now() + REFRESH_COOLDOWN_MS)

                if ((response?.scheduled_kinds ?? []).length === 0) {
                    if (isManual) {
                        lemonToast.info('No health checks are registered for this project.')
                    }
                    return
                }

                for (let i = 0; i < REFRESH_POLL_COUNT; i++) {
                    await breakpoint(REFRESH_POLL_INTERVAL_MS)
                    actions.loadHealthIssues()
                }
            } catch (error: unknown) {
                if (error instanceof ApiError && error.status === 429) {
                    const retryAfterSeconds = Number(error.headers?.get('Retry-After'))
                    if (!isNaN(retryAfterSeconds) && retryAfterSeconds > 0) {
                        actions.setNextRefreshAvailableAt(Date.now() + retryAfterSeconds * 1000)
                    }
                    if (isManual) {
                        lemonToast.warning(`Refresh available again ${error.formattedRetryAfter ?? 'in a few minutes'}`)
                    }
                } else if (isManual) {
                    lemonToast.error('Failed to refresh health checks')
                }
            }
        },
        loadHealthIssuesSuccess: () => {
            const { webAnalyticsHealthStatus, hasAuthorizedUrls, overallHealthStatus, issuesByKind } = values
            if (webAnalyticsHealthStatus && overallHealthStatus.status !== 'loading') {
                actions.reportWebAnalyticsHealthStatus({
                    has_pageviews: webAnalyticsHealthStatus.isSendingPageViews,
                    has_pageleaves: webAnalyticsHealthStatus.isSendingPageLeaves,
                    has_scroll_depth: webAnalyticsHealthStatus.isSendingPageLeavesScroll,
                    has_web_vitals: webAnalyticsHealthStatus.isSendingWebVitals,
                    has_authorized_urls: hasAuthorizedUrls,
                    has_reverse_proxy: !issuesByKind.reverse_proxy,
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

    afterMount(({ actions, values }) => {
        actions.loadHealthIssues()

        const { nextRefreshAvailableAt } = values
        if (nextRefreshAvailableAt === null || nextRefreshAvailableAt <= Date.now()) {
            actions.refreshHealthChecks(false)
        }
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
