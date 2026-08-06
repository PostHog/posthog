import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { Setting } from '~/scenes/settings/types'

/**
 * Kept apart from settingsLogic so consumers (e.g. command palette search) can gate on
 * setting flags without statically importing the full SettingsMap component graph.
 */
export const matchesFlagDefinition = (
    flagKey: Pick<Setting, 'flag'>['flag'],
    featureFlags: FeatureFlagsSet
): boolean => {
    // No flag condition
    if (!flagKey) {
        return true
    }

    const flagsArray = Array.isArray(flagKey) ? flagKey : [flagKey]
    for (const flagCondition of flagsArray) {
        // Tuple flag condition ([flag, value])
        if (Array.isArray(flagCondition)) {
            const [flag, value] = flagCondition
            const isConditionMet = featureFlags[FEATURE_FLAGS[flag]] === value
            if (!isConditionMet) {
                return false
            }
            // Negated flag condition (`!${FeatureFlagKey}`)
        } else if (flagCondition.startsWith('!')) {
            const flag = flagCondition.slice(1) as keyof typeof FEATURE_FLAGS
            const isConditionMet = !featureFlags[FEATURE_FLAGS[flag]]
            if (!isConditionMet) {
                return false
            }
            // Normal flag condition (FeatureFlagKey)
        } else {
            const flag = flagCondition as keyof typeof FEATURE_FLAGS
            const isConditionMet = !!featureFlags[FEATURE_FLAGS[flag]]
            if (!isConditionMet) {
                return false
            }
        }
    }
    return true
}
