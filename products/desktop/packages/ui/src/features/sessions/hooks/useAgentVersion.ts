import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { isAgentVersion } from "@posthog/ui/utils/agentVersion";

/**
 * Returns the connected agent's version for the given task, or `undefined`
 * if no session is active or the agent hasn't reported a version yet.
 */
export function useAgentVersion(
  taskId: string | undefined,
): string | undefined {
  return useSessionStore((s) => {
    if (!taskId) return undefined;
    const taskRunId = s.taskIdIndex[taskId];
    if (!taskRunId) return undefined;
    return s.sessions[taskRunId]?.agentVersion;
  });
}

/**
 * Returns true when the connected agent's version satisfies the given semver
 * range. Fails closed when the version is unknown — feature gates stay off.
 *
 * Examples:
 *   useIsAgentVersion(taskId, ">=0.40.1")
 *   useIsAgentVersion(taskId, ">1.0.0")
 *   useIsAgentVersion(taskId, ">=0.40.0 <1.0.0")
 */
export function useIsAgentVersion(
  taskId: string | undefined,
  range: string,
): boolean {
  const version = useAgentVersion(taskId);
  return isAgentVersion(version, range);
}
