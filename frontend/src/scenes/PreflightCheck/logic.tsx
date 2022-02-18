import { kea } from 'kea'
import React from 'react'
import api from 'lib/api'
import { PreflightStatus, Realm } from '~/types'
import { preflightLogicType } from './logicType'
import posthog from 'posthog-js'
import { getAppContext } from 'lib/utils/getAppContext'
import { toast } from 'react-toastify'
import { teamLogic } from 'scenes/teamLogic'

type PreflightMode = 'experimentation' | 'live'

export interface EnvironmentConfigOption {
    key: string
    metric: string
    value: string
}

export const preflightLogic = kea<preflightLogicType<EnvironmentConfigOption, PreflightMode>>({
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
                toast(
                    <>
                        You've switched globally to&nbsp;project{' '}
                        <b style={{ whiteSpace: 'pre' }}>{values.currentTeam?.name}</b>
                    </>
                )
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setPreflightMode: () => ['/preflight', { mode: values.preflightMode }],
    }),
    urlToAction: ({ actions }) => ({
        '/preflight': (_, { mode }) => {
            if (mode) {
                actions.setPreflightMode(mode as PreflightMode, true)
            }
        },
    }),
})
