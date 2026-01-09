import posthog from 'posthog-js'

import { FEATURE_FLAGS } from './constants'
import { inStorybook, inStorybookTestRunner } from './utils'

// Please remember that in Javascript months are 0-indexed
// January is 0 and December is 11
const getToday = (): { month: number; day: number } => {
    const localTime = new Date()

    const month = localTime.getMonth()
    const day = localTime.getDate()

    return { month, day }
}

// Always wrap the exported functions with this to prevent them
// from returning true on Storybook which would cause a bunch of flakey snapshots
const wrapWithStorybookCheck = (fn: () => boolean) => () => {
    if (inStorybook() || inStorybookTestRunner()) {
        return false
    }

    return fn()
}

export const isChristmas = wrapWithStorybookCheck(() => {
    if (posthog.getFeatureFlag(FEATURE_FLAGS.CHRISTMAS_OVERRIDE)) {
        return true
    }

    // Some days around Christmas is still Christmas for decoration purposes :)
    const { month, day } = getToday()
    return month === 11 && day >= 15 && day <= 28
})

export const isHalloween = wrapWithStorybookCheck(() => {
    if (posthog.getFeatureFlag(FEATURE_FLAGS.HALLOWEEN_OVERRIDE)) {
        return true
    }

    // Some days around Halloween is still Halloween for decoration purposes :)
    const { month, day } = getToday()
    return month === 9 && day >= 28 && day <= 31
})
