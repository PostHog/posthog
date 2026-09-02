import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";

export function useSignalSourceConfigs(options?: { enabled?: boolean }) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<SignalSourceConfig[]>(
    ["signals", "source-configs", projectId],
    (client) =>
      projectId
        ? client.listSignalSourceConfigs(projectId)
        : Promise.resolve([]),
    {
      enabled: !!projectId && (options?.enabled ?? true),
      staleTime: 30_000,
    },
  );
}
