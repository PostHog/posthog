import type { HedgeHogMode as HedgeHogModeType } from '@posthog/hedgehog-mode'
import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import posthog from 'posthog-js'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { HedgehogConfig } from '~/types'

import type { hedgehogModeLogicType } from './hedgehogModeLogicType'

export const hedgehogModeLogic = kea<hedgehogModeLogicType>([
    path(['hedgehog', 'hedgehogModeLogic']),
    connect({
        values: [userLogic, ['user'], membersLogic, ['members']],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    }),
    actions({
        setHedgehogModeEnabled: (enabled: boolean) => ({ enabled }),
        addAccessory: (accessory: string) => ({ accessory }),
        removeAccessory: (accessory: string) => ({ accessory }),
        patchHedgehogConfig: (config: Partial<HedgehogConfig>) => ({ config }),
        clearLocalConfig: true,
        loadRemoteConfig: true,
        updateRemoteConfig: (config: Partial<HedgehogConfig>) => ({ config }),
        setGameRef: (ref: React.RefObject<HTMLDivElement>) => ({ ref }),
        ensureGameLoaded: true,
    }),

    reducers(() => ({
        localConfig: [
            null as Partial<HedgehogConfig> | null,
            {
                clearLocalConfig: () => null,
                patchHedgehogConfig: (state, { config }) => ({
                    ...(state ?? {}),
                    ...config,
                }),
            },
        ],
        gameRef: [
            null as React.RefObject<HTMLDivElement> | null,
            {
                setGameRef: (_, { ref }) => ref,
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

        game: [
            null as HedgeHogModeType | null,
            {
                loadGame: async () => {
                    // We lazy load the SDK and the game
                    const { HedgeHogMode } = await import('@posthog/hedgehog-mode')

                    const hedgeHogMode = new HedgeHogMode({
                        assetsUrl: '/static/hedgehog-mode/',
                        platformSelector:
                            '.border, .border-t, .LemonButton--primary, .LemonButton--secondary:not(.LemonButton--status-alt:not(.LemonButton--active)), .LemonInput, .LemonSelect, .LemonTable, .LemonSwitch--bordered',
                    })
                    await hedgeHogMode.render(values.gameRef)

                    lemonToast.success('Loaded hedgehog mode')

                    return hedgeHogMode as any
                },
            },
        ],
    })),

    selectors({
        partialHedgehogConfig: [
            (s) => [s.localConfig, s.remoteConfig],
            (localConfig, remoteConfig): Partial<HedgehogConfig> => {
                return {
                    ...(remoteConfig ?? {}),
                    ...(localConfig ?? {}),
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

        setGameRef: ({ ref }) => {
            if (ref && values.hedgehogModeEnabled) {
                actions.ensureGameLoaded()
            }
        },

        ensureGameLoaded: () => {
            if (values.gameLoading || values.game || !values.gameRef) {
                return
            }
            actions.loadGame()
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
