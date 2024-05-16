import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

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
    })),

    selectors({
        partialHedgehogConfig: [
            (s) => [s.localConfig, userLogic.selectors.user],
            (localConfig, user): Partial<HedgehogConfig> => {
                return {
                    ...(user?.hedgehog_config ?? {}),
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

            await new Promise<void>((res) => {
                // TODO: Fix the rate limiting of this...
                userLogic.findMounted()?.actions.updateUser(
                    {
                        // We use the partialHedgehogConfig here to avoid including defaults
                        hedgehog_config: values.partialHedgehogConfig,
                    },
                    res
                )
            })

            await breakpoint(100)

            actions.clearLocalConfig()
        },
    })),

    afterMount(({ actions }) => {
        posthog.getEarlyAccessFeatures((features) => {
            const relatedEAF = features.find((x) => x.flagKey === FEATURE_FLAGS.HEDGEHOG_MODE)
            if (relatedEAF) {
                if (posthog.getFeatureFlag(FEATURE_FLAGS.HEDGEHOG_MODE)) {
                    actions.setHedgehogModeEnabled(true)
                }

                posthog.updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.HEDGEHOG_MODE, false)
            }
        })
    }),
])
