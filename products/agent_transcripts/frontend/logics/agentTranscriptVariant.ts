import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

/** The experiment arms that ask for the transcript. `test` also offers a merch code for an approved transcript. */
export type AgentTranscriptRequestVariant = 'control' | 'test'

const REQUEST_VARIANTS: readonly AgentTranscriptRequestVariant[] = ['control', 'test']

/**
 * The arm the organization is in, or null when it is not asked. Reading the flag through the
 * `featureFlagLogic` proxy records the experiment exposure.
 */
export function agentTranscriptRequestVariant(featureFlags: FeatureFlagsSet): AgentTranscriptRequestVariant | null {
    const value = featureFlags[FEATURE_FLAGS.AGENT_TRANSCRIPT_REQUEST]

    return REQUEST_VARIANTS.find((variant) => variant === value) ?? null
}
