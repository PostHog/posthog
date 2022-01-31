import { kea } from 'kea'
import api from 'lib/api'
import { PreflightStatus, Realm } from '~/types'
import { preflightLogicType } from './logicType'
import posthog from 'posthog-js'
import { getAppContext } from 'lib/utils/getAppContext'

type PreflightMode = 'experimentation' | 'live'

export const preflightLogic = kea<preflightLogicType<PreflightMode>>({
    path: ['scenes', 'PreflightCheck', 'preflightLogic'],
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
            (preflight): Record<string, string>[] => {
                // Returns the preflight config options to display in the /instance/status page

                const RELEVANT_CONFIGS = [
                    {
                        key: 'site_url',
                        label: 'Site URL',
                    },
                    { key: 'email_service_available', label: 'Email service available' },
                ]

                if (!preflight) {
                    return []
                }
                // @ts-ignore
                return RELEVANT_CONFIGS.map((config) => ({ metric: config.label, value: preflight[config.key] }))
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
            const preflight = getAppContext()?.preflight
            if (preflight) {
                actions.loadPreflightSuccess(preflight)
            } else if (!values.preflight) {
                actions.loadPreflight()
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
