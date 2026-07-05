import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { humanFriendlyDuration } from 'lib/utils/durations'
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

import {
    HealthCheck,
    HealthCheckAction,
    HealthCheckCategory,
    HealthCheckId,
    HealthCheckStatus,
    OverallHealthStatus,
} from './healthCheckTypes'
import type { webAnalyticsHealthLogicType } from './webAnalyticsHealthLogicType'

/**
 * Static presentational config for the web analytics checks. The pass/fail decision and the
 * underlying detection live entirely in the backend Temporal health checks (one `kind` per row
 * in posthog_healthissue); this page only renders the result. Copy, actions, and docs links are
 * pure presentation and stay here.
 */
interface WebHealthCheckConfig {
    id: HealthCheckId
    kind: string
    category: HealthCheckCategory
    title: string
    passingDescription: string
    failingDescription: string
    passingAction?: HealthCheckAction
    failingAction?: HealthCheckAction
    docsUrl?: string
    urgent?: boolean
}

const INSTALL_GUIDE_ACTION: HealthCheckAction = {
    label: 'View installation guide',
    to: 'https://posthog.com/docs/libraries/js',
}

const WEB_HEALTH_CHECKS: WebHealthCheckConfig[] = [
    {
        id: HealthCheckId.PAGEVIEW_EVENTS,
        kind: 'no_live_events',
        category: 'events',
        title: '$pageview',
        passingDescription:
            'Events are flowing in as expected. Head over to the Web Analytics tab to start reviewing your analytics!',
        failingDescription: 'Complete the PostHog installation to start seeing events in your dashboard.',
        failingAction: INSTALL_GUIDE_ACTION,
        docsUrl: 'https://posthog.com/docs/product-analytics/capture-events',
        urgent: true,
    },
    {
        id: HealthCheckId.PAGELEAVE_EVENTS,
        kind: 'no_pageleave_events',
        category: 'events',
        title: '$pageleave',
        passingDescription: 'Bounce rate and session duration are accurate!',
        failingDescription: 'Without $pageleave events, bounce rate and session duration might be inaccurate.',
        failingAction: INSTALL_GUIDE_ACTION,
        docsUrl: 'https://posthog.com/docs/web-analytics/dashboard#bounce-rate',
    },
    {
        id: HealthCheckId.SCROLL_DEPTH,
        kind: 'scroll_depth',
        category: 'events',
        title: 'Scroll depth',
        passingDescription: 'Scroll tracking is enabled! Tracking how far users scroll on each page.',
        failingDescription: 'Enable scroll depth to see how far users read your content before leaving.',
        failingAction: INSTALL_GUIDE_ACTION,
        docsUrl: 'https://posthog.com/docs/web-analytics/scroll-depth',
    },
    {
        id: HealthCheckId.AUTHORIZED_URLS,
        kind: 'authorized_urls',
        category: 'configuration',
        title: 'Authorized URLs',
        passingDescription:
            'Authorized URLs configured. Your analytics are filtered to only include traffic from your domains.',
        failingDescription:
            "No authorized URLs configured. Some filters won't work correctly until you let us know what domains you are sending events from.",
        passingAction: { label: 'Manage domains', to: urls.settings('environment-web-analytics') },
        failingAction: { label: 'Add domains', to: urls.settings('environment-web-analytics') },
    },
    {
        id: HealthCheckId.REVERSE_PROXY,
        kind: 'reverse_proxy',
        category: 'configuration',
        title: 'Reverse proxy',
        passingDescription: 'Reverse proxy is configured! Your tracking requests are routed through your own domain.',
        failingDescription:
            'A reverse proxy routes PostHog requests through your own domain and helps prevent ad blockers from blocking tracking. Some metrics may not be accurate until this is configured.',
        failingAction: { label: 'Set up reverse proxy', to: urls.settings('organization-proxy') },
        docsUrl: 'https://posthog.com/docs/advanced/proxy',
        urgent: true,
    },
    {
        id: HealthCheckId.WEB_VITALS,
        kind: 'web_vitals',
        category: 'performance',
        title: '$web_vitals',
        passingDescription: 'LCP, INP, and CLS are being tracked. You can monitor your real user experience!',
        failingDescription:
            'Core Web Vitals (LCP, INP, CLS) measure real user experience. Google uses these metrics for search ranking.',
        passingAction: { label: 'View Web Vitals', to: '/web/web-vitals' },
        failingAction: {
            label: 'Enable Web Vitals',
            to: urls.settings('environment-web-analytics', 'web-vitals-autocapture'),
        },
        docsUrl: 'https://posthog.com/docs/web-analytics/web-vitals',
    },
]

export const webAnalyticsHealthLogic = kea<webAnalyticsHealthLogicType>([
    path(['scenes', 'web-analytics', 'health', 'webAnalyticsHealthLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeamIdStrict']],
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
        setNow: (now: number) => ({ now }),
        startCooldownCountdown: true,
    }),

    reducers({
        nextRefreshAvailableAt: [
            null as number | null,
            { persist: true },
            {
                setNextRefreshAvailableAt: (_, { timestamp }) => timestamp,
            },
        ],
        now: [
            Date.now(),
            {
                setNow: (_, { now }) => now,
            },
        ],
    }),

    loaders(({ values }) => ({
        healthIssues: {
            __default: null as HealthIssuesResponse | null,
            loadHealthIssues: async (): Promise<HealthIssuesResponse> => {
                return await api.get<HealthIssuesResponse>(
                    `api/projects/${values.currentTeamIdStrict}/health_issues/?status=active&dismissed=false`
                )
            },
        },
    })),

    selectors({
        activeIssuesByKind: [
            (s) => [s.healthIssues],
            (healthIssues: HealthIssuesResponse | null): Record<string, HealthIssue> => {
                const byKind: Record<string, HealthIssue> = {}
                for (const issue of healthIssues?.results ?? []) {
                    byKind[issue.kind] ??= issue
                }
                return byKind
            },
        ],

        allChecks: [
            (s) => [s.activeIssuesByKind, s.healthIssuesLoading, s.healthIssues],
            (
                activeIssuesByKind: Record<string, HealthIssue>,
                loading: boolean,
                healthIssues: HealthIssuesResponse | null
            ): HealthCheck[] => {
                return WEB_HEALTH_CHECKS.map((config) => {
                    // Show loading only on the first load (no data yet), like the rest of the health UI.
                    if (loading && !healthIssues) {
                        return {
                            id: config.id,
                            category: config.category,
                            title: config.title,
                            description: 'Checking...',
                            status: 'loading' as HealthCheckStatus,
                        }
                    }

                    const issue = activeIssuesByKind[config.kind]
                    if (!issue) {
                        return {
                            id: config.id,
                            category: config.category,
                            title: config.title,
                            description: config.passingDescription,
                            status: 'success' as HealthCheckStatus,
                            action: config.passingAction,
                            docsUrl: config.docsUrl,
                            urgent: config.urgent,
                        }
                    }

                    // Critical backend severity surfaces as an error, everything else as a warning.
                    const status: HealthCheckStatus = issue.severity === 'critical' ? 'error' : 'warning'
                    return {
                        id: config.id,
                        category: config.category,
                        title: config.title,
                        description: config.failingDescription,
                        status,
                        action: config.failingAction,
                        docsUrl: config.docsUrl,
                        urgent: config.urgent,
                    }
                })
            },
        ],

        checksByCategory: [
            (s) => [s.allChecks],
            (allChecks: HealthCheck[]): Record<HealthCheckCategory, HealthCheck[]> => ({
                events: allChecks.filter((check) => check.category === 'events'),
                configuration: allChecks.filter((check) => check.category === 'configuration'),
                performance: allChecks.filter((check) => check.category === 'performance'),
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

        refreshDisabledReason: [
            (s) => [s.nextRefreshAvailableAt, s.now],
            (nextRefreshAvailableAt: number | null, now: number): string | null => {
                if (nextRefreshAvailableAt === null || nextRefreshAvailableAt <= now) {
                    return null
                }
                const secondsLeft = Math.ceil((nextRefreshAvailableAt - now) / 1000)
                return `A refresh just ran. Available again in ${humanFriendlyDuration(secondsLeft, { maxUnits: 2 })}`
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        setNextRefreshAvailableAt: ({ timestamp }) => {
            if (timestamp !== null && timestamp > Date.now()) {
                actions.startCooldownCountdown()
            }
        },
        startCooldownCountdown: () => {
            // Tick `now` once a second so the button's countdown stays live, and tear the
            // ticker down as soon as the cooldown clears. Re-adding with the same key replaces
            // any in-flight ticker, and the plugin pauses it while the tab is hidden.
            cache.disposables.add(() => {
                const intervalId = setInterval(() => {
                    actions.setNow(Date.now())
                    const { nextRefreshAvailableAt } = values
                    if (nextRefreshAvailableAt === null || nextRefreshAvailableAt <= Date.now()) {
                        cache.disposables.dispose('cooldownTicker')
                    }
                }, 1000)
                return () => clearInterval(intervalId)
            }, 'cooldownTicker')
        },
        refreshHealthChecks: async ({ isManual }, breakpoint) => {
            const { overallHealthStatus } = values
            actions.reportWebAnalyticsHealthRefreshed({
                overall_status: overallHealthStatus.status,
                passed_count: overallHealthStatus.passedCount,
            })

            try {
                const response = await api.create<{
                    scheduled_kinds: string[]
                    kinds_failed: string[]
                    team_id: number
                }>(`api/projects/${values.currentTeamIdStrict}/health_issues/refresh/`)
                breakpoint()

                actions.setNextRefreshAvailableAt(Date.now() + REFRESH_COOLDOWN_MS)

                if ((response?.scheduled_kinds ?? []).length === 0) {
                    if (isManual) {
                        lemonToast.info('No health checks are registered for this project.')
                    }
                    return
                }

                if (isManual) {
                    lemonToast.success('Refreshing health checks...', { autoClose: 2000 })
                }
                for (let i = 0; i < REFRESH_POLL_COUNT; i++) {
                    await breakpoint(REFRESH_POLL_INTERVAL_MS)
                    actions.loadHealthIssues()
                }
            } catch (error: unknown) {
                if (error instanceof ApiError) {
                    if (error.status === 429) {
                        // A refresh ran recently; honour the cooldown the backend reports.
                        const retryAfterSeconds = Number(error.headers?.get('Retry-After'))
                        if (!isNaN(retryAfterSeconds) && retryAfterSeconds > 0) {
                            actions.setNextRefreshAvailableAt(Date.now() + retryAfterSeconds * 1000)
                        }
                        if (isManual) {
                            lemonToast.warning(
                                `Refresh available again ${error.formattedRetryAfter ?? 'in a few minutes'}`
                            )
                        }
                    } else if (isManual) {
                        lemonToast.error('Failed to refresh health checks')
                    }
                    return
                }
                // Re-throw BreakPointError (and any other non-API error) so kea can cancel this
                // listener. Swallowing it lets a superseded poll keep running alongside the new
                // one, doubling the request rate.
                throw error
            }
        },
        loadHealthIssuesSuccess: () => {
            const { activeIssuesByKind, overallHealthStatus } = values
            if (overallHealthStatus.status !== 'loading') {
                actions.reportWebAnalyticsHealthStatus({
                    has_pageviews: !activeIssuesByKind['no_live_events'],
                    has_pageleaves: !activeIssuesByKind['no_pageleave_events'],
                    has_scroll_depth: !activeIssuesByKind['scroll_depth'],
                    has_web_vitals: !activeIssuesByKind['web_vitals'],
                    has_authorized_urls: !activeIssuesByKind['authorized_urls'],
                    has_reverse_proxy: !activeIssuesByKind['reverse_proxy'],
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
        } else {
            // A cooldown from a previous visit is still ticking down; keep the button's countdown live.
            actions.setNow(Date.now())
            actions.startCooldownCountdown()
        }
    }),
])
