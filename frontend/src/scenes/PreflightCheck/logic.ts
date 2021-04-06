import { kea } from 'kea'
import api from 'lib/api'
import { PreflightStatus } from '~/types'
import { preflightLogicType } from './logicType'
import posthog from 'posthog-js'

export const preflightLogic = kea<preflightLogicType<PreflightStatus>>({
    loaders: ({ actions }) => ({
        preflight: [
            null as PreflightStatus | null,
            {
                loadPreflight: async () => {
                    const response = await api.get('_preflight/')
                    actions.registerInstrumentationProps()
                    return response
                },
            },
        ],
    }),
    actions: {
        registerInstrumentationProps: true,
    },
    selectors: {
        socialAuthAvailable: [
            (s) => [s.preflight],
            (preflight: PreflightStatus | null) =>
                preflight && Object.values(preflight.available_social_auth_providers).filter((i) => i).length,
        ],
        realm: [
            (s) => [s.preflight],
            (preflight: PreflightStatus | null): 'cloud' | 'hosted' | null => {
                if (!preflight) {
                    return null
                }
                return preflight.cloud ? 'cloud' : 'hosted'
            },
        ],
    },
    listeners: ({ values }) => ({
        registerInstrumentationProps: async (_, breakpoint) => {
            await breakpoint(100)
            if (posthog && values.preflight) {
                posthog.register({
                    posthog_version: values.preflight.posthog_version,
                    realm: values.realm,
                    ee_enabled: values.preflight.ee_enabled,
                    ee_available: values.preflight.ee_available,
                    email_service_available: values.preflight.email_service_available,
                })
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPreflight()
        },
    }),
})
