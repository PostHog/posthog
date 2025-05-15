import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

// NOTE: When using this hook, you use the key of FEATURE_FLAGS as the parameter.
// For example, useFeatureFlag('HOMEPAGE_MAX')
export const useFeatureFlag = (flag: keyof typeof FEATURE_FLAGS, match?: string): boolean => {
    const { featureFlags } = useValues(featureFlagLogic)

    if (match) {
        return featureFlags[FEATURE_FLAGS[flag]] === match
    }

    return !!featureFlags[FEATURE_FLAGS[flag]]
}
