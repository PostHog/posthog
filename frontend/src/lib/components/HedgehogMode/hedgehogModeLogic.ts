import type { HedgeHogMode } from '@posthog/hedgehog-mode'
import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
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
        clearLocalConfig: true,
        loadRemoteConfig: true,
        updateRemoteConfig: (config: Partial<HedgehogConfig>) => ({ config }),
        syncGame: true,
        syncFromState: true,
    }),

    reducers(() => ({
        hedgehogMode: [
            null as HedgeHogMode | null,
            {
                setHedgehogMode: (_, { hedgeHogMode }) => hedgeHogMode,
            },
        ],
    })),

    loaders(({ values }) => ({
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
                    let newConfig: Partial<HedgehogConfig>

                    let payload = {
                        ...values.remoteConfig,
                        ...config,
                    }

                    const mountedToolbarConfigLogic = toolbarConfigLogic.findMounted()
                    if (mountedToolbarConfigLogic) {
                        // If toolbarConfigLogic is mounted, we're inside the Toolbar
                        if (!mountedToolbarConfigLogic.values.isAuthenticated) {
                            return null
                        }
                        newConfig = await (await toolbarFetch(endpoint, 'PATCH', payload)).json()
                    } else {
                        newConfig = await api.update(endpoint, payload)
                    }

                    return newConfig ?? null
                },
            },
        ],
    })),

    selectors({
        hedgehogConfig: [
            (s) => [s.remoteConfig],
            (remoteConfig): HedgehogConfig => {
                return {
                    enabled: false,
                    use_as_profile: false,
                    party_mode_enabled: false,
                    actor_options: {
                        color: null,
                        accessories: [],
                        ai_enabled: true,
                        interactions_enabled: true,
                        controls_enabled: true,
                        id: 'player',
                        player: true,
                    },
                    ...remoteConfig,
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
            actions.updateRemoteConfig({
                enabled,
            })

            posthog.capture(enabled ? 'hedgehog mode enabled' : 'hedgehog mode disabled')
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
            const { hedgehogMode, hedgehogConfig } = values
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

        syncFromState: () => {
            const { hedgehogMode } = values
            if (!hedgehogMode) {
                return
            }
            const state = hedgehogMode.stateManager?.getState()
            const player = state?.hedgehogsById?.['player']

            if (!player) {
                return
            }

            const lastPlayerState = JSON.stringify(values.hedgehogConfig.actor_options)
            const currentPlayerState = JSON.stringify(player)
            if (lastPlayerState !== currentPlayerState) {
                // On change, update the remote config
                actions.updateRemoteConfig({
                    actor_options: player,
                })
            }
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

    afterMount(({ actions, cache }) => {
        const loadedUser = userLogic.findMounted()?.values.user
        if (loadedUser) {
            actions.loadRemoteConfigSuccess(loadedUser.hedgehog_config ?? {})
        } else {
            actions.loadRemoteConfig()
        }

        cache.syncInterval = setInterval(() => {
            actions.syncFromState()
        }, 1000)
    }),

    beforeUnmount(({ cache }) => {
        if (cache.syncInterval) {
            clearInterval(cache.syncInterval)
            cache.syncInterval = null
        }
    }),
])
