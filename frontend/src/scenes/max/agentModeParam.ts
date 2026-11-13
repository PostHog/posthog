import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'

import { MODE_DEFINITIONS } from './max-constants'

/**
 * Reads an agent mode from a link. Only the modes that the mode picker offers are accepted. An unknown value, or a
 * mode whose feature flag is off, gives auto mode (`null`).
 */
export function agentModeFromParam(value: string, featureFlags: FeatureFlagsSet): AgentMode | null {
    if (value === AgentMode.Research) {
        return featureFlags[FEATURE_FLAGS.MAX_DEEP_RESEARCH] ? AgentMode.Research : null
    }
    if (value === AgentMode.Plan) {
        return featureFlags[FEATURE_FLAGS.PHAI_PLAN_MODE] ? AgentMode.Plan : null
    }
    if (!Object.hasOwn(MODE_DEFINITIONS, value)) {
        return null
    }
    const mode = value as keyof typeof MODE_DEFINITIONS
    const flag = MODE_DEFINITIONS[mode].flag
    return flag && !featureFlags[FEATURE_FLAGS[flag]] ? null : mode
}
