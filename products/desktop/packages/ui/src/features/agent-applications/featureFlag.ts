/**
 * Gates the whole agent-platform surface in PostHog: the Fleet tab
 * content (list + per-agent detail) and the always-on Agent Builder dock. The
 * Scouts tab is unaffected. Mirrors the `agent-platform` flag on the PostHog
 * side (`FEATURE_FLAGS.AGENT_PLATFORM`). Hidden until GA.
 */
export const AGENT_PLATFORM_FLAG = "agent-platform";
