import { kea } from 'kea'
import React from 'react'
import api from 'lib/api'
import { PreflightStatus, Realm } from '~/types'
import posthog from 'posthog-js'
import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { IconSwapHoriz } from 'lib/components/icons'
import { userLogic } from 'scenes/userLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { preflightLogicType } from './preflightLogicType'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'

type PreflightMode = 'experimentation' | 'live'

export interface PreflightItemInterface {
    name: string
    status: boolean
    caption?: string
    failedState?: 'warning' | 'not-required'
}

export interface CheckInterface extends PreflightItemInterface {
    id: string
}

export interface EnvironmentConfigOption {
    key: string
    metric: string
    value: string
}

export const preflightLogic = kea<preflightLogicType<CheckInterface, EnvironmentConfigOption, PreflightMode>>({
    path: ['scenes', 'PreflightCheck', 'preflightLogic'],
    connect: {
        values: [teamLogic, ['currentTeam']],
    },
    loaders: {
        preflight: [
            null as PreflightStatus | null,
            {
                loadPreflight: async () => await api.get('_preflight/'),
            },
        ],
    },
    actions: {
        registerInstrumentationProps: true,
        setPreflightMode: (mode: PreflightMode | null, noReload?: boolean) => ({ mode, noReload }),
        handlePreflightFinished: true,
    },
    reducers: {
        preflightMode: [
            null as PreflightMode | null,
            {
                setPreflightMode: (_, { mode }) => mode,
            },
        ],
    },
    selectors: {
        checks: [
            (s) => [s.preflight, s.preflightMode],
            (preflight, preflightMode) => {
                return [
                    {
                        id: 'database',
                        name: 'Database (Postgres)',
                        status: preflight?.db,
                    },
                    {
                        id: 'backend',
                        name: 'Backend server (Django)',
                        status: preflight?.django,
                    },
                    {
                        id: 'redis',
                        name: 'Cache & queue (Redis)',
                        status: preflight?.redis,
                    },
                    {
                        id: 'celery',
                        name: 'Background jobs (Celery)',
                        status: preflight?.celery,
                    },
                    {
                        id: 'plugins',
                        name: 'Plugin server (Node)',
                        status: preflight?.plugins,
                        caption: preflightMode === 'experimentation' ? 'Required in production environments' : '',
                        failedState: preflightMode === 'experimentation' ? 'warning' : 'error',
                    },
                    {
                        id: 'frontend',
                        name: 'Frontend build (Webpack)',
                        status: true,
                    },
                    {
                        id: 'tls',
                        name: 'SSL/TLS certificate',
                        status: window.location.protocol === 'https:',
                        caption:
                            preflightMode === 'experimentation'
                                ? 'Not required for experimentation mode'
                                : 'Install before ingesting real user data',
                        failedState: preflightMode === 'experimentation' ? 'not-required' : 'warning',
                    },
                ] as CheckInterface[]
            },
        ],
        isReady: [
            (s) => [s.preflight, s.preflightMode],
            (preflight, preflightMode) => {
                return (
                    preflight &&
                    preflight.django &&
                    preflight.db &&
                    preflight.redis &&
                    preflight.celery &&
                    (preflightMode === 'experimentation' || preflight.plugins)
                )
            },
        ],
        socialAuthAvailable: [
            (s) => [s.preflight],
            (preflight): boolean =>
                Boolean(preflight && Object.values(preflight.available_social_auth_providers).filter((i) => i).length),
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
                return Boolean(preflight && (!preflight.site_url || preflight.site_url != window.location.origin))
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
                // @ts-ignore
                return RELEVANT_CONFIGS.map((config) => ({
                    key: config.key,
                    metric: config.label,
                    value: preflight[config.key],
                }))
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        handlePreflightFinished: () => {
            router.actions.push(urls.signup())
        },
        loadPreflightSuccess: () => {
            actions.registerInstrumentationProps()
        },
        registerInstrumentationProps: async (_, breakpoint) => {
            await breakpoint(100)
            if (posthog && values.preflight) {
                posthog.register({
                    posthog_version: values.preflight.posthog_version,
                    realm: values.realm,
                    email_service_available: values.preflight.email_service_available,
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
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            const appContext = getAppContext()
            const preflight = appContext?.preflight
            const switchedTeam = appContext?.switched_team
            if (preflight) {
                actions.loadPreflightSuccess(preflight)
            } else if (!values.preflight) {
                actions.loadPreflight()
            }
            if (switchedTeam) {
                lemonToast.info(
                    <>
                        You've switched to&nbsp;project <b>{values.currentTeam?.name}</b>
                    </>,
                    {
                        button: {
                            label: 'Switch back',
                            action: () => userLogic.actions.updateCurrentTeam(switchedTeam),
                        },
                        icon: <IconSwapHoriz />,
                    }
                )
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setPreflightMode: () => ['/preflight', { mode: values.preflightMode }],
    }),
    urlToAction: ({ actions, values }) => ({
        '/preflight': (_, { mode }) => {
            if (values.preflightMode !== mode) {
                actions.setPreflightMode(mode ?? (null as PreflightMode | null), true)
            }
        },
    }),
})
