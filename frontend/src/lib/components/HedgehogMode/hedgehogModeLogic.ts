import type { HedgeHogMode } from '@posthog/hedgehog-mode'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
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
        setHedgehogMode: (hedgeHogMode: HedgeHogMode) => ({ hedgeHogMode }),
        setHedgehogModeEnabled: (enabled: boolean) => ({ enabled }),
        patchHedgehogConfig: (config: Partial<HedgehogConfig>) => ({ config }),
        clearLocalConfig: true,
        loadRemoteConfig: true,
        updateRemoteConfig: (config: Partial<HedgehogConfig>) => ({ config }),
        syncGame: true,
    }),

    reducers(() => ({
        hedgehogMode: [
            null as HedgeHogMode | null,
            {
                setHedgehogMode: (_, { hedgeHogMode }) => hedgeHogMode,
            },
        ],
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
                    ai_enabled: true,
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

    listeners(({ actions, values, cache }) => ({
        setHedgehogModeEnabled: ({ enabled }) => {
            actions.patchHedgehogConfig({
                enabled,
            })

            posthog.capture(enabled ? 'hedgehog mode enabled' : 'hedgehog mode disabled')
        },

        patchHedgehogConfig: async () => {
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

        syncGame: () => {
            const { hedgehogMode, hedgehogConfig, members } = values
            if (!hedgehogMode || !hedgehogConfig) {
                return
            }

            if (!hedgehogConfig.enabled) {
                cache.hedgehogs = {}
                return
            }

            // TODO: Sync members with game

            // const hedgehogs: Record<string, HedgehogActor> = (cache.hedgehogs = cache.hedgehogs || {})

            // console.log('hedgehogs', hedgehogs)

            // const membersWithHedgehogConfig = members?.filter(
            //     (x) => x.user.hedgehog_config && x.user.uuid !== values.user?.uuid
            // )

            // if (!hedgehogConfig.party_mode_enabled) {
            //     // Remove all members
            //     membersWithHedgehogConfig?.forEach((x) => {
            //         if (hedgehogs[x.user.uuid]) {
            //             hedgehogs[x.user.uuid].destroy()
            //             delete hedgehogs[x.user.uuid]
            //         }
            //     })
            // } else {
            //     // Sync members
            //     membersWithHedgehogConfig?.forEach((x) => {
            //         const combinedHedgehogConfig: HedgehogActorOptions = {
            //             ...hedgehogConfig,
            //             ...x.user.hedgehog_config,
            //             id: x.user.uuid,
            //             player: false,
            //             // Reset some params to default
            //             skin: 'default',
            //             // Finally some settings are forced
            //             controls_enabled: false,
            //         }
            //         if (!hedgehogs[x.user.uuid]) {
            //             hedgehogs[x.user.uuid] = game.spawnHedgehog(combinedHedgehogConfig)
            //         } else {
            //             hedgehogs[x.user.uuid].updateOptions(combinedHedgehogConfig)
            //         }
            //     })
            // }

            // if (!hedgehogs.player) {
            //     hedgehogs.player = game.spawnHedgehog({
            //         ...hedgehogConfig,
            //         id: 'player',
            //         player: true,
            //         onClick: () => {},
            //     })
            // } else {
            //     hedgehogs.player.updateOptions({
            //         ...hedgehogConfig,
            //     })
            // }
        },
    })),

    subscriptions(({ actions, values }) => ({
        hedgehogConfig: () => {
            if (values.hedgehogModeEnabled) {
                actions.ensureAllMembersLoaded()
            }
            actions.syncGame()
        },
        hedgehogMode: () => actions.syncGame(),
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
