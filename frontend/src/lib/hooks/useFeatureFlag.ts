import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'

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
