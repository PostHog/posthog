import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { HedgehogColorOptions, HedgehogConfig } from '~/types'

import type { hedgehogBuddyLogicType } from './hedgehogBuddyLogicType'

export const COLOR_TO_FILTER_MAP: Record<HedgehogColorOptions, string> = {
    red: 'hue-rotate(340deg) saturate(300%) brightness(90%)',
    green: 'hue-rotate(60deg) saturate(100%)',
    blue: 'hue-rotate(210deg) saturate(300%) brightness(90%)',
    purple: 'hue-rotate(240deg)',
    dark: 'brightness(70%)',
    light: 'brightness(130%)',
    sepia: 'sepia(100%) saturate(300%) brightness(70%)',
    invert: 'invert(100%)',
    'invert-hue': 'invert(100%) hue-rotate(180deg)',
    greyscale: 'saturate(0%)',
}

export const hedgehogBuddyLogic = kea<hedgehogBuddyLogicType>([
    path(['hedgehog', 'hedgehogBuddyLogic']),
    actions({
        setHedgehogModeEnabled: (enabled: boolean) => ({ enabled }),
        addAccessory: (accessory: string) => ({ accessory }),
        removeAccessory: (accessory: string) => ({ accessory }),
        patchHedgehogConfig: (config: Partial<HedgehogConfig>) => ({ config }),
        clearLocalConfig: true,
        loadRemoteConfig: true,
        updateRemoteConfig: (config: Partial<HedgehogConfig>) => ({ config }),
    }),

    reducers(() => ({
        localConfig: [
            null as Partial<HedgehogConfig> | null,
            {
                clearLocalConfig: () => null,
                patchHedgehogConfig: (state, { config }) => ({
                    ...state,
                    ...config,
                }),
            },
        ],
    })),

    loaders(({ values, actions }) => ({
        remoteConfig: [
            null as Partial<HedgehogConfig> | null,
            {
                loadRemoteConfig: async () => {
                    const endpoint = '/api/users/@me/hedgehog_config'
                    const mountedToolbarConfigLogic = toolbarConfigLogic.findMounted()
                    if (mountedToolbarConfigLogic) {
                        // If toolbarConfigLogic is mounted, we're inside the Toolbar
                        if (!mountedToolbarConfigLogic.values.isAuthenticated) {
                            return null
                        }
                        return await (await toolbarFetch(endpoint, 'GET')).json()
                    }
                    return await api.get<Partial<HedgehogConfig>>(endpoint)
                },

                updateRemoteConfig: async ({ config }) => {
                    const endpoint = '/api/users/@me/hedgehog_config'
                    const localConfig = values.localConfig
                    let newConfig: Partial<HedgehogConfig>

                    const mountedToolbarConfigLogic = toolbarConfigLogic.findMounted()
                    if (mountedToolbarConfigLogic) {
                        // If toolbarConfigLogic is mounted, we're inside the Toolbar
                        if (!mountedToolbarConfigLogic.values.isAuthenticated) {
                            return null
                        }
                        newConfig = await (await toolbarFetch(endpoint, 'PATCH', config)).json()
                    } else {
                        newConfig = await api.update(endpoint, config)
                    }

                    if (localConfig === values.localConfig) {
                        actions.clearLocalConfig()
                    }

                    return newConfig ?? null
                },
            },
        ],
    })),

    selectors({
        partialHedgehogConfig: [
            (s) => [s.localConfig, s.remoteConfig],
            (localConfig, remoteConfig): Partial<HedgehogConfig> => {
                return {
                    ...remoteConfig,
                    ...localConfig,
                }
            },
        ],

        hedgehogConfig: [
            (s) => [s.partialHedgehogConfig],
            (partialHedgehogConfig): HedgehogConfig => {
                return {
                    enabled: false,
                    use_as_profile: false,
                    color: null,
                    accessories: [],
                    walking_enabled: true,
                    interactions_enabled: true,
                    controls_enabled: true,
                    party_mode_enabled: false,
                    ...partialHedgehogConfig,
                }
            },
        ],

        hedgehogModeEnabled: [
            (s) => [s.hedgehogConfig],
            (hedgehogConfig): boolean => {
                return !!hedgehogConfig.enabled
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setHedgehogModeEnabled: ({ enabled }) => {
            actions.patchHedgehogConfig({
                enabled,
            })

            posthog.capture(enabled ? 'hedgehog mode enabled' : 'hedgehog mode disabled')
        },

        addAccessory: ({ accessory }) => {
            actions.patchHedgehogConfig({
                accessories: [...(values.hedgehogConfig.accessories ?? []), accessory],
            })
        },

        removeAccessory: ({ accessory }) => {
            actions.patchHedgehogConfig({
                accessories: (values.hedgehogConfig.accessories ?? []).filter((acc) => acc !== accessory),
            })
        },

        patchHedgehogConfig: async (_, breakpoint) => {
            await breakpoint(1000)
            actions.updateRemoteConfig(values.hedgehogConfig)
        },

        updateRemoteConfigSuccess: ({ remoteConfig }) => {
            const theUserLogic = userLogic.findMounted()

            if (theUserLogic) {
                userLogic
                    .findMounted()
                    ?.actions.loadUserSuccess({ ...theUserLogic.values.user, hedgehog_config: remoteConfig } as any)
            }
        },
    })),

    afterMount(({ actions }) => {
        const loadedUser = userLogic.findMounted()?.values.user
        if (loadedUser) {
            actions.loadRemoteConfigSuccess(loadedUser.hedgehog_config ?? {})
        } else {
            actions.loadRemoteConfig()
        }
    }),
])
