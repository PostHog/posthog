import type {
  DryRunToolRequest,
  DryRunToolResult,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation } from "@tanstack/react-query";

interface DryRunArgs {
  toolId: string;
  body: DryRunToolRequest;
}

/**
 * Execute a persisted tool once in a sandbox (POST …/dry_run). No cache
 * invalidation — dry-run is a side-effect-free probe. Throttled (429) and
 * unavailable (503) are returned as {@link DryRunToolResult} outcomes, not
 * errors, so the panel handles them explicitly; callers must NOT retry a 429.
 */
export function useDryRunRevisionTool(idOrSlug: string, revisionId: string) {
  const client = useAuthenticatedClient();
  return useMutation<DryRunToolResult, Error, DryRunArgs>({
    mutationFn: ({ toolId, body }) =>
      client.dryRunRevisionTool(idOrSlug, revisionId, toolId, body),
  });
}
