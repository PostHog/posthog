import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { HedgehogConfig, MinimalHedgehogConfig } from '~/types'

import { sanitizeHedgehogConfig } from './hedgehog-mode-utils'
import type { hedgehogModeLogicType } from './hedgehogModeLogicType'
import { HedgehogModeInterface } from './types'

export const hedgehogModeLogic = kea<hedgehogModeLogicType>([
    path(['hedgehog', 'hedgehogModeLogic']),
    connect({
        values: [userLogic, ['user'], membersLogic, ['members']],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    }),
    actions({
        setHedgehogMode: (hedgeHogMode: HedgehogModeInterface) => ({ hedgeHogMode }),
        setHedgehogModeEnabled: (enabled: boolean) => ({ enabled }),
        toggleHedgehogMode: true,
        loadRemoteConfig: true,
        updateRemoteConfig: (config: Partial<HedgehogConfig>) => ({ config }),
        syncGame: true,
        syncFromState: true,
    }),

    reducers(() => ({
        hedgehogMode: [
            null as HedgehogModeInterface | null,
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
                        ...values.hedgehogConfig,
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
                return sanitizeHedgehogConfig({
                    ...remoteConfig,
                })
            },
        ],

        hedgehogModeEnabled: [
            (s) => [s.hedgehogConfig],
            (hedgehogConfig): boolean => {
                return !!hedgehogConfig.enabled
            },
        ],

        minimalHedgehogConfig: [
            (s) => [s.hedgehogConfig],
            (hedgehogConfig): MinimalHedgehogConfig => {
                const forcedHedeghogProfile: MinimalHedgehogConfig = {
                    use_as_profile: true,
                    color: hedgehogConfig?.actor_options?.color,
                    skin: hedgehogConfig?.actor_options?.skin,
                    accessories: hedgehogConfig?.actor_options?.accessories,
                }

                return forcedHedeghogProfile
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setHedgehogModeEnabled: ({ enabled }) => {
            actions.updateRemoteConfig({
                enabled,
            })

            posthog.capture(enabled ? 'hedgehog mode enabled' : 'hedgehog mode disabled')
        },
        toggleHedgehogMode: () => {
            actions.setHedgehogModeEnabled(!values.hedgehogModeEnabled)
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

            // Sync the actor options to the game
            hedgehogMode.stateManager?.setHedgehog(hedgehogConfig.actor_options)
        },

        syncFromState: () => {
            const { hedgehogMode } = values
            if (!hedgehogMode) {
                return
            }
            const state = hedgehogMode.stateManager?.getState()
            const player = state?.options

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
