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
const wrapWithStorybookCheck = <F extends (...args: any[]) => boolean>(
    fn: F
): ((...args: Parameters<F>) => boolean) => {
    return (...args: Parameters<F>): boolean => {
        if (inStorybook() || inStorybookTestRunner()) {
            return false
        }

        return fn(...args)
    }
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

type Holiday = 'christmas' | 'halloween'
type HolidayMatcher<T> = {
    [key in Holiday]: T
}

export const holidaysMatcher = <T,>(matcher: HolidayMatcher<T>, orElse: T): T => {
    // Return the default value in Storybook to prevent flakey snapshots
    if (inStorybook() || inStorybookTestRunner()) {
        return orElse
    }

    if (matcher.christmas && isChristmas()) {
        return matcher.christmas
    }
    if (matcher.halloween && isHalloween()) {
        return matcher.halloween
    }

    return orElse
}
