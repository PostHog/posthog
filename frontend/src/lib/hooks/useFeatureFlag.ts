import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export const useFeatureFlag = (flag: keyof typeof FEATURE_FLAGS, match?: string): boolean => {
    const { featureFlags } = useValues(featureFlagLogic)

    if (match) {
        return featureFlags[FEATURE_FLAGS[flag]] === match
    }

    return !!featureFlags[FEATURE_FLAGS[flag]]
}
