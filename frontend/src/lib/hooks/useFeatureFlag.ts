import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

export const useFeatureFlag = (flag: keyof typeof FEATURE_FLAGS, match?: string): boolean => {
    const { featureFlags } = useValues(featureFlagLogic)

    // If a match is provided, we're only actually gonna check it if not running on Storybook
    // On storybook we'll simply set the flag to be available and in that case we just ignore the match
    // and check the flag itself
    if (match && !inStorybook() && !inStorybookTestRunner()) {
        return featureFlags[FEATURE_FLAGS[flag]] === match
    }

    return !!featureFlags[FEATURE_FLAGS[flag]]
}

/** The flag value once it is final, or `null` while the /flags response can still turn the flag on. */
export const useResolvedFeatureFlag = (flag: keyof typeof FEATURE_FLAGS): boolean | null => {
    const enabled = useFeatureFlag(flag)
    const { receivedServerFeatureFlags } = useValues(featureFlagLogic)
    return enabled || receivedServerFeatureFlags ? enabled : null
}
