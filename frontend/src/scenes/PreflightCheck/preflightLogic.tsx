import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { getAppContext } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

import { PreflightStatus, Realm } from '~/types'

import type { preflightLogicType } from './preflightLogicType'

export type PreflightMode = 'experimentation' | 'live'

export type PreflightCheckStatus = 'validated' | 'error' | 'warning' | 'optional'

export interface PreflightItem {
    name: string
    status: PreflightCheckStatus
    caption?: string
    id: string
}

export interface PreflightCheckSummary {
    summaryString: string
    summaryStatus: PreflightCheckStatus
}

export interface EnvironmentConfigOption {
    key: string
    metric: string
    value: string
}

export const preflightLogic = kea<preflightLogicType>([
    path(['scenes', 'PreflightCheck', 'preflightLogic']),
    loaders({
        preflight: [
            null as PreflightStatus | null,
            {
                loadPreflight: async () => {
                    const response = await api.get<PreflightStatus>('_preflight/')
                    return response
                },
            },
        ],
    }),
    actions({
        registerInstrumentationProps: true,
        setPreflightMode: (mode: PreflightMode | null, noReload?: boolean) => ({ mode, noReload }),
        handlePreflightFinished: true,
        setChecksManuallyExpanded: (expanded: boolean | null) => ({ expanded }),
        revalidatePreflight: true,
    }),
    reducers({
        preflightMode: [
            null as PreflightMode | null,
            {
                setPreflightMode: (_, { mode }) => mode,
            },
        ],
        areChecksManuallyExpanded: [
            null as boolean | null,
            {
                setChecksManuallyExpanded: (_, { expanded }) => expanded,
            },
        ],
    }),
    selectors({
        checks: [
            (s) => [s.preflight, s.preflightMode],
            (preflight, preflightMode) => {
                const preflightItems = [
                    {
                        id: 'database',
                        name: 'Application database · Postgres',
                        status: preflight?.db ? 'validated' : 'error',
                    },
                    {
                        id: 'clickhouse',
                        name: 'Analytics database · ClickHouse',
                        status: preflight?.clickhouse ? 'validated' : 'error',
                    },
                    {
                        id: 'kafka',
                        name: 'Queue · Kafka',
                        status: preflight?.kafka ? 'validated' : 'error',
                    },
                    {
                        id: 'backend',
                        name: 'Backend server · Django',
                        status: preflight?.django ? 'validated' : 'error',
                    },
                    {
                        id: 'redis',
                        name: 'Cache · Redis',
                        status: preflight?.redis
                            ? 'validated'
                            : preflightMode === 'experimentation'
                              ? 'warning'
                              : 'error',
                        caption:
                            !preflight?.redis && preflightMode === 'experimentation'
                                ? 'Required in production environments'
                                : undefined,
                    },
                    {
                        id: 'celery',
                        name: 'Background jobs · Celery',
                        status: preflight?.celery
                            ? 'validated'
                            : preflightMode === 'experimentation'
                              ? 'warning'
                              : 'error',
                        caption:
                            !preflight?.celery && preflightMode === 'experimentation'
                                ? 'Required in production environments'
                                : undefined,
                    },
                    {
                        id: 'plugins',
                        name: 'Plugin server · Node',
                        status: preflight?.plugins
                            ? 'validated'
                            : preflightMode === 'experimentation'
                              ? 'warning'
                              : 'error',
                        caption:
                            !preflight?.plugins && preflightMode === 'experimentation'
                                ? 'Required in production environments'
                                : undefined,
                    },
                    {
                        id: 'frontend',
                        name: 'Frontend build · Webpack',
                        status: 'validated', // Always validated if we're showing the preflight check
                    },
                    {
                        id: 'tls',
                        name: 'SSL/TLS certificate',
                        status:
                            window.location.protocol === 'https:'
                                ? 'validated'
                                : preflightMode === 'experimentation'
                                  ? 'optional'
                                  : 'warning',
                        caption:
                            !(window.location.protocol === 'https:') && preflightMode === 'experimentation'
                                ? 'Not required for experimentation mode'
                                : 'Set up before ingesting real user data',
                    },
                ]

                if (preflight?.object_storage || preflight?.is_debug) {
                    /** __for now__, only prompt debug users if object storage is unhealthy **/
                    preflightItems.push({
                        id: 'object_storage',
                        name: 'Object Storage',
                        status: preflight?.object_storage ? 'validated' : 'warning',
                        caption: preflight?.object_storage
                            ? undefined
                            : 'Some features will not work without object storage',
                    })
                }

                return preflightItems as PreflightItem[]
            },
        ],
        checksSummary: [
            (s) => [s.checks],
            (checks): PreflightCheckSummary => {
                const statusCounts = {} as Record<PreflightCheckStatus, number>
                if (checks.length > 0) {
                    for (const check of checks) {
                        statusCounts[check.status] = (statusCounts[check.status] || 0) + 1
                    }
                }

                let summaryString = ''
                let summaryStatus: PreflightCheckStatus = 'validated'

                if (statusCounts.validated) {
                    summaryString += `${statusCounts.validated} successful, `
                }
                if (statusCounts.warning) {
                    summaryString += `${statusCounts.warning} warning${statusCounts.warning > 1 ? 's' : ''}, `
                    summaryStatus = 'warning'
                }
                if (statusCounts.error) {
                    summaryString += `${statusCounts.error} error${statusCounts.error > 1 ? 's' : ''}, `
                    summaryStatus = 'error'
                }
                if (statusCounts.optional) {
                    summaryString += `${statusCounts.optional} optional, `
                }

                return { summaryString: summaryString.slice(0, -2), summaryStatus: summaryStatus }
            },
        ],
        areChecksExpanded: [
            (s) => [s.checksSummary, s.areChecksManuallyExpanded],
            (checksSummary, areChecksManuallyExpanded) => {
                return areChecksManuallyExpanded ?? checksSummary?.summaryStatus !== 'validated'
            },
        ],
        socialAuthAvailable: [
            (s) => [s.preflight],
            (preflight): boolean =>
                Boolean(preflight && Object.values(preflight.available_social_auth_providers).filter((i) => i).length),
        ],
        objectStorageAvailable: [
            (s) => [s.preflight],
            (preflight): boolean => Boolean(preflight && preflight.object_storage),
        ],
        realm: [
            (s) => [s.preflight],
            (preflight): Realm | null => {
                if (!preflight) {
                    return null
                }
                return preflight.realm
            },
        ],
        siteUrlMisconfigured: [
            (s) => [s.preflight],
            (preflight): boolean => {
                if (process?.env.STORYBOOK) {
                    // Disable the "site URL misconfigured" warning in Storybook. This is for consistent snapshots
                    // - when opening Storybook in the browser or when updating the snapshots in CI, the origin is
                    // http://localhost:6006, but in the local dockerized setup http://host.docker.internal:6006
                    return false
                }
                const isMismatchPresent =
                    !!preflight && (!preflight.site_url || preflight.site_url != window.location.origin)
                if (
                    isMismatchPresent &&
                    preflight.site_url === 'http://localhost:8010' &&
                    window.location.origin === 'http://localhost:8000'
                ) {
                    // Local development setup using the old port - we have a warning in DebugNotice for this
                    return false
                }
                return isMismatchPresent
            },
        ],
        configOptions: [
            (s) => [s.preflight],
            (preflight): EnvironmentConfigOption[] => {
                // Returns the preflight config options to display in the /instance/status page

                const RELEVANT_CONFIGS = [
                    {
                        key: 'site_url',
                        label: 'Site URL',
                    },
                ]

                if (!preflight) {
                    return []
                }
                return RELEVANT_CONFIGS.map((config) => ({
                    key: config.key,
                    metric: config.label,
                    value: preflight[config.key],
                }))
            },
        ],
        isCloudOrDev: [
            (s) => [s.preflight],
            (preflight): boolean | undefined => {
                return preflight?.cloud || preflight?.is_debug
            },
        ],
        isTest: [(s) => [s.preflight], (preflight) => !!preflight?.is_test],
        isHobby: [(s) => [s.isCloudOrDev, s.isTest], (isCloudOrDev, isTest) => !isCloudOrDev && !isTest],
        isCloud: [
            (s) => [s.preflight],
            (preflight): boolean | undefined => {
                return preflight?.cloud
            },
        ],
        isDev: [
            (s) => [s.preflight],
            (preflight): boolean | undefined => {
                return preflight?.is_debug
            },
        ],
        disableNavigationHooks: [
            (s) => [s.preflight],
            (preflight): boolean | undefined => {
                return preflight?.dev_disable_navigation_hooks
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        handlePreflightFinished: () => {
            router.actions.push(urls.signup())
        },
        loadPreflightSuccess: () => {
            actions.registerInstrumentationProps()
            actions.setChecksManuallyExpanded(values.areChecksManuallyExpanded || null)
        },
        registerInstrumentationProps: async (_, breakpoint) => {
            await breakpoint(100)
            if (posthog && values.preflight) {
                const appContext = getAppContext()

                posthog.register({
                    realm: values.realm,
                    email_service_available: values.preflight.email_service_available,
                    slack_service_available: values.preflight.slack_service?.available,
                    commit_sha: appContext?.commit_sha,
                })

                if (values.preflight.site_url) {
                    posthog.group('instance', values.preflight.site_url, {
                        site_url: values.preflight.site_url,
                    })
                }
            }
        },
        setPreflightMode: async ({ mode, noReload }) => {
            if (mode && !noReload) {
                actions.loadPreflight()
            }
        },
        revalidatePreflight: () => {
            // The TLS check MUST be in the array returned by the `checks` selector
            const tlsCheckResult = values.checks.find((check) => check.id === 'tls') as PreflightItem
            if (tlsCheckResult.status === 'warning') {
                // Full page reload is needed to revalidate whether the page is served over HTTPS
                window.location.reload()
            } else {
                // Otherwise, just fetch from the preflight endpoint within the logic
                actions.loadPreflight()
            }
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            const appContext = getAppContext()
            const preflight = appContext?.preflight
            if (preflight) {
                actions.loadPreflightSuccess(preflight)
            } else if (!values.preflight) {
                actions.loadPreflight()
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setPreflightMode: () => ['/preflight', { mode: values.preflightMode }],
    })),
    urlToAction(({ actions, values }) => ({
        '/preflight': (_, { mode }) => {
            if (values.preflightMode !== mode) {
                actions.setPreflightMode(mode ?? (null as PreflightMode | null), true)
            }
        },
    })),
])
