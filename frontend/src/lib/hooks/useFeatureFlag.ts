import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, type FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

type UseFeatureFlagOptions = {
    deferUntilResolved?: boolean
    enabled?: boolean
}

export const useFeatureFlag = (
    flag: keyof typeof FEATURE_FLAGS | undefined,
    match?: string,
    options?: UseFeatureFlagOptions
): boolean => {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!flag || options?.enabled === false) {
        return false
    }

    const featureFlagKey = FEATURE_FLAGS[flag]

    if (options?.deferUntilResolved) {
        const featureFlagsWithSnapshot = featureFlags as FeatureFlagsSet & { toJSON?: () => FeatureFlagsSet }
        const resolvedFeatureFlags = featureFlagsWithSnapshot.toJSON?.() ?? featureFlags

        if (resolvedFeatureFlags[featureFlagKey] === undefined) {
            return false
        }
    }

    // If a match is provided, we're only actually gonna check it if not running on Storybook
    // On storybook we'll simply set the flag to be available and in that case we just ignore the match
    // and check the flag itself
    if (match && !inStorybook() && !inStorybookTestRunner()) {
        return featureFlags[featureFlagKey] === match
    }

    return !!featureFlags[featureFlagKey]
}
