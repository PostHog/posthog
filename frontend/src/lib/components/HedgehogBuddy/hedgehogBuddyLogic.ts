import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

import { HedgehogColorOptions, HedgehogConfig } from '~/types'

import type { hedgehogBuddyLogicType } from './hedgehogBuddyLogicType'
import { AccessoryInfo, standardAccessories } from './sprites/sprites'

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
        addAccessory: (accessory: AccessoryInfo) => ({ accessory }),
        removeAccessory: (accessory: AccessoryInfo) => ({ accessory }),
        patchHedgehogConfig: (config: Partial<HedgehogConfig>) => ({ config }),
        clearLocalConfig: true,
    }),

    reducers(() => ({
        localConfig: [
            null as Partial<HedgehogConfig>,
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
        availableAccessories: [
            () => [],
            () => {
                return Object.keys(standardAccessories)
            },
        ],

        hedgehogConfig: [
            (s) => [s.localConfig, userLogic.selectors.user],
            (localConfig, user): HedgehogConfig => {
                return {
                    ...(user.hedgehog_config ?? {}),
                    ...(localConfig ?? {}),
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

    listeners(({ actions }) => ({
        setHedgehogModeEnabled: ({ enabled }) => {
            actions.patchHedgehogConfig({
                enabled,
            })

            posthog.capture(enabled ? 'hedgehog mode enabled' : 'hedgehog mode disabled')
        },

        setHedgehogConfig: async ({ config }, breakpoint) => {
            await breakpoint(1000)

            await new Promise<void>((res) => {
                userLogic.findMounted()?.actions.updateUser(
                    {
                        hedgehog_config: config,
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
