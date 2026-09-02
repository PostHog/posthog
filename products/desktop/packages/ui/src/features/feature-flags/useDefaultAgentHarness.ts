import {
  type AgentRuntime,
  DEFAULT_AGENT_RUNTIME,
  DEFAULT_HARNESS_FLAG,
  isAgentRuntime,
} from "@posthog/shared";
import { useFeatureFlagPayload } from "@posthog/ui/features/feature-flags/useFeatureFlagPayload";

/**
 * The fleet-wide default harness for a user with no saved runtime choice.
 * Remote-configured via DEFAULT_HARNESS_FLAG's payload so the default can
 * roll back to ACP without a release. An unmatched flag or an invalid
 * payload keeps the app on DEFAULT_AGENT_RUNTIME.
 */
export function useDefaultAgentHarness(): AgentRuntime {
  const payload = useFeatureFlagPayload(DEFAULT_HARNESS_FLAG);
  return isAgentRuntime(payload) ? payload : DEFAULT_AGENT_RUNTIME;
}
