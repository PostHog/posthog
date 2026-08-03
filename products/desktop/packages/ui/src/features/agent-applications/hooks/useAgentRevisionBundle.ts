import type { BundleFile } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/** A revision's bundle files (agent.md, skill bodies, tool sources + schemas). */
export function useAgentRevisionBundle(
  idOrSlug: string,
  revisionId: string | null | undefined,
) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<BundleFile[]>(
    agentApplicationsKeys.bundle(projectId, idOrSlug, revisionId ?? ""),
    (client) =>
      revisionId
        ? client.getAgentRevisionBundle(idOrSlug, revisionId)
        : Promise.resolve([]),
    { enabled: !!projectId && !!idOrSlug && !!revisionId, staleTime: 30_000 },
  );
}
