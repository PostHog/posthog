import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'

import type { hedgehogBuddyLogicType } from './hedgehogBuddyLogicType'
import { AccessoryInfo, standardAccessories } from './sprites/sprites'

export const hedgehogBuddyLogic = kea<hedgehogBuddyLogicType>([
    path(['hedgehog', 'hedgehogBuddyLogic']),
    actions({
        setHedgehogModeEnabled: (enabled: boolean) => ({ enabled }),
        addAccessory: (accessory: AccessoryInfo) => ({ accessory }),
        removeAccessory: (accessory: AccessoryInfo) => ({ accessory }),
        setFreeMovement: (enabled: boolean) => ({ enabled }),
        setInteractWithElements: (enabled: boolean) => ({ enabled }),
        setKeyboardControlsEnabled: (enabled: boolean) => ({ enabled }),
        setImageFilter: (enabled: boolean) => ({ enabled }),
        setColor: (color: string) => ({ color }),
    }),

    reducers(() => ({
        freeMovement: [
            true,
            { persist: true },
            {
                setFreeMovement: (_, { enabled }) => enabled,
            },
        ],

        interactWithElements: [
            true,
            { persist: true },
            {
                setInteractWithElements: (_, { enabled }) => enabled,
            },
        ],

        keyboardControlsEnabled: [
            true,
            { persist: true },
            {
                setKeyboardControlsEnabled: (_, { enabled }) => enabled,
            },
        ],
        color: [
            'default',
            { persist: true },
            {
                setColor: (_, { color }) => color,
            },
        ],

        accessories: [
            [] as AccessoryInfo[],
            { persist: true },
            {
                addAccessory(state, { accessory }) {
                    return [...state]
                        .filter((oldOne) => {
                            return accessory.group !== oldOne.group
                        })
                        .concat([accessory])
                },
                removeAccessory(state, { accessory }) {
                    return state.filter((x) => x !== accessory)
                },
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
        hedgehogModeEnabled: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.HEDGEHOG_MODE],
        ],

        imageFilter: [
            (s) => [s.color],
            (color) => {
                // green, red, blue, yellow, dark, light, default, sepia, invert, invert-hue
                switch (color) {
                    case 'green':
                        return 'hue-rotate(120deg)'
                    case 'red':
                        return 'hue-rotate(0deg)'
                    case 'blue':
                        return 'hue-rotate(240deg)'
                    case 'yellow':
                        return 'hue-rotate(60deg)'
                    case 'dark':
                        return 'brightness(70%)'
                    case 'light':
                        return 'brightness(130%)'
                    case 'sepia':
                        return 'sepia(100%) saturate(300%) brightness(70%)'
                    case 'invert':
                        return 'invert(100%)'
                    case 'invert-hue':
                        return 'invert(100%) hue-rotate(180deg)'
                    default:
                        return 'none'
                }
            },
        ],
    }),

    listeners(() => ({
        setHedgehogModeEnabled: ({ enabled }) => {
            posthog.updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.HEDGEHOG_MODE, enabled)
            posthog.capture(enabled ? 'hedgehog mode enabled' : 'hedgehog mode disabled')
        },
    })),
])
