import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import posthog from 'posthog-js'

import type { hedgehogBuddyLogicType } from './hedgehogBuddyLogicType'
import { AccessoryInfo, standardAccessories } from './sprites/sprites'

export type HedgehogColorOptions =
    | 'green'
    | 'red'
    | 'blue'
    | 'purple'
    | 'dark'
    | 'light'
    | 'sepia'
    | 'invert'
    | 'invert-hue'
    | 'greyscale'

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
        setFreeMovement: (enabled: boolean) => ({ enabled }),
        setInteractWithElements: (enabled: boolean) => ({ enabled }),
        setKeyboardControlsEnabled: (enabled: boolean) => ({ enabled }),
        setImageFilter: (enabled: boolean) => ({ enabled }),
        setColor: (color: HedgehogColorOptions | null) => ({ color }),
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
            null as HedgehogColorOptions | null,
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

        hedgehogModeEnabled: [
            false,
            { persist: true },
            {
                setHedgehogModeEnabled: (_, { enabled }) => enabled,
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

        imageFilter: [
            (s) => [s.color],
            (color): string | null => {
                return color ? COLOR_TO_FILTER_MAP[color] : null
            },
        ],
    }),

    listeners(() => ({
        setHedgehogModeEnabled: ({ enabled }) => {
            posthog.capture(enabled ? 'hedgehog mode enabled' : 'hedgehog mode disabled')
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
