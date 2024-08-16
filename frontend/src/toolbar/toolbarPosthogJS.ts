import { FeatureFlagKey } from 'lib/constants'
import PostHog from 'posthog-js-lite'
import { useEffect, useState } from 'react'

const DEFAULT_API_KEY = 'sTMFPsFhdP1Ssg'

const runningOnPosthog = !!window.POSTHOG_APP_CONTEXT
const apiKey = runningOnPosthog ? window.JS_POSTHOG_API_KEY : DEFAULT_API_KEY
const apiHost = runningOnPosthog ? window.JS_POSTHOG_HOST : 'https://internal-t.posthog.com'
// const flagsApiHost = runningOnPosthog ? window.JS_POSTHOG_FLAGS_HOST : 'https://feature-flags-do-not-block.posthog.com' // need to commit this too but commented because unused

export const toolbarPosthogJS = new PostHog(apiKey || DEFAULT_API_KEY, {
    host: apiHost,
    // featureFlagsHost: flagsApiHost, // need to update posthog-js first I think before this can be committed
    defaultOptIn: false, // must call .optIn() before any events are sent
    persistence: 'memory', // We don't want to persist anything, all events are in-memory
    persistence_name: apiKey + '_toolbar', // We don't need this but it ensures we don't accidentally mess with the standard persistence
    preloadFeatureFlags: false,
})

if (runningOnPosthog && window.JS_POSTHOG_SELF_CAPTURE) {
    toolbarPosthogJS.debug()
}

export const useToolbarFeatureFlag = (flag: FeatureFlagKey, match?: string): boolean => {
    const [flagValue, setFlagValue] = useState<boolean | string | undefined>(toolbarPosthogJS.getFeatureFlag(flag))

    useEffect(() => {
        return toolbarPosthogJS.onFeatureFlag(flag, (value) => setFlagValue(value))
    }, [flag, match])

    if (match) {
        return flagValue === match
    }

    return !!flagValue
}
