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
    }),

    reducers(() => ({
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
    }),

    listeners(() => ({
        setHedgehogModeEnabled: ({ enabled }) => {
            posthog.updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.HEDGEHOG_MODE, enabled)
            posthog.capture(enabled ? 'hedgehog mode enabled' : 'hedgehog mode disabled')
        },
    })),
])
