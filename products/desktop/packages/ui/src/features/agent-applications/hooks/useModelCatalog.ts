import type { ModelCatalog } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";

// Levels rarely change and the auto-level preview needs them even while the
// catalog request is in flight; the authoritative values still come from the
// endpoint. Models are left empty until the fetch resolves.
const FALLBACK: ModelCatalog = {
  models: [],
  levels: {
    low: ["anthropic/claude-haiku-4.5", "openai/gpt-5-mini"],
    medium: ["anthropic/claude-sonnet-4.6", "openai/gpt-5"],
    high: ["anthropic/claude-opus-4.7", "openai/gpt-5-pro"],
  },
};

/**
 * The served-model catalog + curated auto-level → model map, from
 * `GET …/agent_applications/models/` (which proxies the AI gateway catalog).
 * Feeds the model browser and the auto-level preview. Falls back to an empty
 * catalog (with the known levels) while loading or if the endpoint is down.
 */
export function useModelCatalog(): {
  catalog: ModelCatalog;
  isLoading: boolean;
} {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const { data, isLoading } = useAuthenticatedQuery<ModelCatalog>(
    ["agent-applications", "model-catalog", projectId],
    (client) => client.getAgentModelCatalog(),
    { enabled: !!projectId, staleTime: 5 * 60_000 },
  );
  return { catalog: data ?? FALLBACK, isLoading };
}
