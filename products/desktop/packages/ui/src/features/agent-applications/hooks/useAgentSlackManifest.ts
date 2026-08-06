import type { AgentSlackManifest } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/** The Slack app manifest for a revision. `enabled` defers until the card shows. */
export function useAgentSlackManifest(
  idOrSlug: string,
  revisionId: string | null | undefined,
  enabled = true,
) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentSlackManifest | null>(
    agentApplicationsKeys.slackManifest(projectId, idOrSlug, revisionId ?? ""),
    (client) =>
      revisionId
        ? client.getAgentSlackManifest(idOrSlug, revisionId)
        : Promise.resolve(null),
    {
      enabled: !!projectId && !!idOrSlug && !!revisionId && enabled,
      staleTime: 60_000,
    },
  );
}
