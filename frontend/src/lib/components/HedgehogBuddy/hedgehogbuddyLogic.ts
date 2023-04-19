import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import type { hedgehogbuddyLogicType } from './hedgehogbuddyLogicType'
import posthog from 'posthog-js'
import { AccessoryInfo, standardAccessories } from './sprites/sprites'

export const hedgehogbuddyLogic = kea<hedgehogbuddyLogicType>([
    path(['hedgehog', 'hedgehogbuddyLogic']),
    actions({
        setHedgehogModeEnabled: (enabled: boolean) => ({ enabled }),
        addAccessory: (accessory: AccessoryInfo) => ({ accessory }),
        removeAccessory: (accessory: AccessoryInfo) => ({ accessory }),
    }),

    reducers(({}) => ({
        hedgehogModeEnabled: [
            false as boolean,
            { persist: true },
            {
                setHedgehogModeEnabled: (_, { enabled }) => enabled,
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
                // Until we figure out how to do this - all accessories are available
                return Object.keys(standardAccessories)
                // return Object.keys(standardAccessories).filter((x) => {
                //     const key = `hedgehog-accessory-${x}`
                //     return featureFlags[key]
                // })
            },
        ],
    }),

    listeners(({}) => ({
        setHedgehogModeEnabled: ({ enabled }) => {
            if (enabled) {
                posthog.capture('hedgehog mode enabled')
            } else {
                posthog.capture('hedgehog mode disabled')
            }
        },
    })),
])
